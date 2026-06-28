"""Document tools (function-calling loop).

Tools expuestas al agente del chat:
  - ``list_documents(modulo_id?)``        →  lista los documentos del
    usuario en la materia o en un módulo puntual.
  - ``read_document(document_id, max_chars?)`` →  concatena los chunks
    del documento y los devuelve truncados a ``max_chars`` (default
    200 000). Devuelve metadata de secciones (visibles y omitidas) para
    que el LLM sepa qué vio y qué no.

El resumen de un documento (``Document.summary``) se genera
únicamente durante la ingestión, en
``app/documents/processing.py``. No es una tool del agente.
"""
from __future__ import annotations

import logging
import re

from sqlalchemy import select

from app.agent.tools.context import ToolContext, ToolResult, err, ok
from app.db.models import Document, DocumentChunk, Modulo
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


# Para lectura completa: cap default 200 000 chars (~50k tokens).
# Suficiente para la mayoría de documentos académicos (proyectos finales,
# libros, papers). El hard cap es el mismo — no se puede pasar.
DEFAULT_MAX_READ_CHARS = 200_000
ABSOLUTE_MAX_READ_CHARS = 200_000


# ── Detección de secciones (heurística) ────────────────────────
# Patrones soportados (todos al inicio de línea, case-insensitive donde aplica):
#   "Sección N" / "Capítulo N" / "Anexo X"
#   "1." / "1.2" / "1.2.3"        (decimal)
#   "1)" / "1 -"                  (listas)
#   "I." / "II." / "III." ...     (romanos)
#   "1. INTRODUCCIÓN"              (decimal + MAYÚSCULAS)
#   Línea en mayúsculas corta     (heurística de título)
_SECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(sección|cap[ií]tulo|anexo|ap[eé]ndice|parte)\s+[\w\d]+", re.IGNORECASE),
    re.compile(r"^\d+(\.\d+){0,3}\.?\s+\S"),
    re.compile(r"^\d+(\.\d+){0,3}\)\s+\S"),
    re.compile(r"^\d+(\.\d+){0,3}\s+-\s+\S"),
    re.compile(r"^[IVX]{1,5}\.?\s+\S"),
)


def _looks_like_heading(line: str) -> bool:
    """Heurística: línea en mayúsculas, corta, sin punto final obligatorio."""
    stripped = line.strip()
    if not stripped or len(stripped) > 80:
        return False
    if not any(pat.match(stripped) for pat in _SECTION_PATTERNS):
        return False
    return True


def _detect_sections(text: str) -> list[str]:
    """Devuelve la lista de headings detectados en el texto, en orden."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or not _looks_like_heading(line):
            continue
        # Limpiamos para deduplicar (mismo heading no aparece 2 veces).
        key = re.sub(r"\s+", " ", line).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out


def _smart_truncate(text: str, cap: int) -> str:
    """Corta ``text`` a ``cap`` chars intentando no romper un párrafo.

    Si hay un ``\\n\\n`` (separador de párrafos) antes del cap, cortamos
    ahí. Si no, cortamos en el último whitespace. Si tampoco hay, corte
    crudo (mejor que nada).
    """
    if len(text) <= cap:
        return text
    window = text[:cap]
    last_para = window.rfind("\n\n")
    if last_para > cap // 2:
        return window[:last_para].rstrip()
    last_ws = window.rfind(" ")
    if last_ws > cap // 2:
        return window[:last_ws].rstrip()
    return window


# ── list_documents ─────────────────────────────────────────────
def list_documents(ctx: ToolContext, modulo_id: int | None = None) -> ToolResult:
    """Lista los documentos del usuario.

    Si se pasa ``modulo_id``, filtra por ese módulo (con check de
    ownership). Si no, devuelve todos los documentos del usuario en la
    materia del chat.
    """
    db = SessionLocal()
    try:
        stmt = (
            select(Document)
            .join(Modulo, Document.modulo_id == Modulo.id)
            .where(Modulo.user_id == ctx.user_id)
            .order_by(Document.created_at.desc(), Document.id.desc())
        )
        if modulo_id is not None:
            modulo = db.get(Modulo, modulo_id)
            if modulo is None or modulo.user_id != ctx.user_id:
                return err(f"módulo {modulo_id} no encontrado o no pertenece al usuario")
            stmt = stmt.where(Document.modulo_id == modulo_id)
        elif ctx.materia_id is not None:
            stmt = stmt.where(Document.materia_id == ctx.materia_id)

        rows = db.execute(stmt).scalars().all()
        items = [
            {
                "id": d.id,
                "modulo_id": d.modulo_id,
                "materia_id": d.materia_id,
                "filename": d.filename,
                "mime": d.mime,
                "size": d.size,
                "status": d.status,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "has_summary": bool(d.summary),
            }
            for d in rows
        ]
        return ok(documents=items, count=len(items))
    except Exception as exc:  # noqa: BLE001
        logger.exception("list_documents tool falló")
        return err(f"list_documents: {exc.__class__.__name__}")
    finally:
        db.close()


# ── read_document ──────────────────────────────────────────────
def read_document(
    ctx: ToolContext,
    document_id: int,
    max_chars: int | None = None,
) -> ToolResult:
    """Lee el contenido completo de un documento (concatenando chunks).

    Truncado a ``max_chars`` (default 200 000) con corte "prolijo" (no
    rompe párrafos). Devuelve metadata de secciones para que el LLM
    sepa exactamente qué vio:

      - ``first_section_seen``   primer heading detectado en el texto
        devuelto (o ``None`` si no se detectaron headings).
      - ``last_section_seen``    último heading dentro del texto devuelto.
      - ``sections_in_returned`` lista completa de headings que están
        en el texto devuelto.
      - ``sections_omitted``     headings que quedaron fuera del corte
        (vacía si no se truncó).
    """
    cap = max_chars if max_chars is not None else DEFAULT_MAX_READ_CHARS
    if cap <= 0:
        return err("max_chars debe ser positivo")
    cap = min(cap, ABSOLUTE_MAX_READ_CHARS)

    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is None or doc.modulo.user_id != ctx.user_id:
            return err(f"documento {document_id} no encontrado o no pertenece al usuario")
        if doc.status != "ready":
            return err(
                f"documento {document_id} no está listo (status={doc.status}); "
                f"esperá a que termine de indexarse"
            )

        chunks = (
            db.execute(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document_id)
                .order_by(DocumentChunk.chunk_index.asc())
            )
            .scalars()
            .all()
        )
        full_text = "\n\n".join(c.text for c in chunks)
        total_chars = len(full_text)
        truncated = total_chars > cap
        text = _smart_truncate(full_text, cap)

        all_sections = _detect_sections(full_text)
        if truncated:
            returned_sections = _detect_sections(text)
            returned_set = {re.sub(r"\s+", " ", s).lower() for s in returned_sections}
            omitted = [s for s in all_sections if re.sub(r"\s+", " ", s).lower() not in returned_set]
        else:
            returned_sections = all_sections
            omitted = []

        first_seen = returned_sections[0] if returned_sections else None
        last_seen = returned_sections[-1] if returned_sections else None

        return ok(
            document_id=doc.id,
            filename=doc.filename,
            mime=doc.mime,
            chunks_total=len(chunks),
            total_chars=total_chars,
            returned_chars=len(text),
            truncated=truncated,
            first_section_seen=first_seen,
            last_section_seen=last_seen,
            sections_in_returned=returned_sections,
            sections_omitted=omitted,
            text=text,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("read_document tool falló")
        return err(f"read_document: {exc.__class__.__name__}")
    finally:
        db.close()
