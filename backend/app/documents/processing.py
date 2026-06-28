"""Document processing pipeline (Fase 4).

Corre dentro de un ``BackgroundTask`` de FastAPI. No comparte la sesión
de SQLAlchemy del request (que ya se cerró); abre su propio ``SessionLocal``
para tener un ciclo de vida claro.

Pasos:
  1. Escribe el archivo físico a ``<upload_dir>/<user_id>/<doc_id>__<safe>``.
  2. Extrae texto con ``parser.extract_text``.
  3. Lo divide en chunks con ``chunker.chunk_text``.
  4. Persiste los chunks en ``document_chunks``.
   5. Pide un resumen a GO (``GoClient.complete``).
  6. Marca el documento ``ready`` (con ``summary``) o ``error`` (con
     ``error_message``) según corresponda.

El archivo físico se guarda **antes** de empezar a parsear, así un fallo
de parser no nos deja con un doc "processing" eterno: queda en
``status='error'`` con el path registrado (no se borra para debugging).
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from google.genai import errors as genai_errors

from app.agent import rag
from app.agent.llm import GoClient
from app.agent.prompts import build_summary_instruction
from app.config import get_settings
from app.db.models import Document, DocumentChunk
from app.db.session import SessionLocal
from app.documents.chunker import chunk_text
from app.documents.parser import ParserError, extract_text

logger = logging.getLogger(__name__)

# Cuántos chars del texto mandamos al LLM para resumir. Suficiente para
# apuntes típicos y bien debajo de los límites de la free tier.
SUMMARY_INPUT_CHARS = 6000
SUMMARY_MAX_TOKENS_HINT = 600


def _safe_filename(filename: str) -> str:
    """Reduce el nombre a algo razonable para usar en disco."""
    name = Path(filename or "documento").name  # descarta cualquier path
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return name[:200] or "documento"


def _user_upload_dir(user_id: int) -> Path:
    settings = get_settings()
    base = Path(settings.upload_dir) / f"user_{user_id}"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _save_file(user_id: int, doc_id: int, filename: str, content: bytes) -> Path:
    target_dir = _user_upload_dir(user_id)
    target = target_dir / f"{doc_id}__{_safe_filename(filename)}"
    target.write_bytes(content)
    return target


def _delete_file_silently(path: str | Path) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        logger.warning("No se pudo borrar el archivo %s", path)


def process_document(
    *,
    document_id: int,
    modulo_id: int,
    user_id: int,
    filename: str,
    content: bytes,
) -> None:
    """Pipeline completo. Idempotente en el sentido de que siempre deja
    el documento con un estado terminal (``ready`` o ``error``).
    """
    start = time.perf_counter()
    settings = get_settings()
    saved_path: Path | None = None
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is None:
            logger.error("process_document: document_id=%s no existe", document_id)
            return
        if doc.modulo_id != modulo_id:
            logger.error(
                "process_document: document_id=%s modulo inconsistente (%s vs %s)",
                document_id,
                doc.modulo_id,
                modulo_id,
            )
            return

        # 1) persistir el archivo
        try:
            saved_path = _save_file(user_id, document_id, filename, content)
            logger.info(
                "documents.process: saved file document_id=%s user_id=%s path=%s size=%d",
                document_id,
                user_id,
                saved_path,
                len(content),
            )
        except OSError as err:
            doc.status = "error"
            doc.error_message = f"No se pudo escribir el archivo: {err}"
            db.commit()
            return

        # 2) extraer texto
        try:
            text = extract_text(filename, doc.mime, content)
        except ParserError as err:
            doc.status = "error"
            doc.error_message = str(err)
            db.commit()
            logger.warning(
                "documents.process: parser error document_id=%s (%s)", document_id, err
            )
            return

        # 3) chunkear
        chunks = chunk_text(text)
        if not chunks:
            doc.status = "error"
            doc.error_message = "El documento no produjo chunks (¿demasiado corto?)"
            db.commit()
            return

        # 4) persistir chunks (borrar los que pudiera haber de un run previo)
        for existing in list(doc.chunks):
            db.delete(existing)
        db.flush()
        for idx, chunk in enumerate(chunks):
            db.add(
                DocumentChunk(
                    document_id=document_id,
                    chunk_index=idx,
                    text=chunk,
                )
            )
        db.flush()

        # 4') indexar en Chroma (Fase 5: RAG). Si falla, el documento
        # queda en 'error' porque sin indexado no se puede responder con
        # citas — es un compromiso explícito de Fase 5. Reintentar
        # resubiendo el archivo.
        try:
            rag.index_document_chunks(
                document_id=document_id,
                modulo_id=modulo_id,
                materia_id=doc.materia_id,
                user_id=user_id,
                filename=filename,
                chunks=chunks,
            )
        except genai_errors.APIError as err:
            logger.exception(
                "documents.process: embedding error al indexar document_id=%s", document_id
            )
            doc.status = "error"
            doc.error_message = f"Error del LLM al indexar: {_short(err)}"
            db.commit()
            return
        except RuntimeError as err:
            # Falta GOOGLE_API_KEY u otro problema de config.
            doc.status = "error"
            doc.error_message = str(err)
            db.commit()
            return
        except Exception as err:  # noqa: BLE001
            logger.exception(
                "documents.process: fallo indexando en Chroma document_id=%s", document_id
            )
            doc.status = "error"
            doc.error_message = f"Error indexando en Chroma: {_short(err)}"
            db.commit()
            return

        # 5) resumen con GO
        try:
            client = GoClient(settings)
            summary = _summarize(client, text, model=settings.summary_model)
        except RuntimeError as err:
            doc.status = "error"
            doc.error_message = str(err)
            db.commit()
            return

        doc.summary = summary
        doc.summary_model = settings.summary_model
        doc.status = "ready"
        doc.error_message = None
        db.commit()

        latency_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "documents.process OK document_id=%s user_id=%s chunks=%d "
            "summary_chars=%d latency_ms=%s",
            document_id,
            user_id,
            len(chunks),
            len(summary or ""),
            latency_ms,
        )
    except Exception as err:  # noqa: BLE001
        logger.exception("documents.process: error inesperado document_id=%s", document_id)
        # Cualquier excepción no controlada: marcar error si el doc todavía existe.
        try:
            doc = db.get(Document, document_id)
            if doc is not None and doc.status == "processing":
                doc.status = "error"
                doc.error_message = f"Error inesperado: {_short(err)}"
                db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("documents.process: no se pudo marcar error en DB")
    finally:
        db.close()


def _summarize(client: GoClient, text: str, *, model: str) -> str:
    """Llama a GO para resumir. Usa el system_instruction dedicado."""
    excerpt = text[:SUMMARY_INPUT_CHARS]
    instruction = build_summary_instruction()
    result = client.complete(
        history=[],
        current_content=excerpt,
        system_instruction=instruction,
        model=model,
    )
    return (result.text or "").strip()


def _short(err: Exception) -> str:
    """Recorta mensajes de error para la columna error_message."""
    raw = str(err).strip()
    if not raw:
        return err.__class__.__name__
    first = raw.splitlines()[0]
    return first[:500]


def remove_file_for_user(user_id: int, path: str) -> None:
    """Helper de delete: borra el archivo físico del usuario si vive
    dentro de su directorio de uploads (defensa contra path traversal).
    """
    user_dir = _user_upload_dir(user_id).resolve()
    try:
        target = Path(path).resolve()
    except (OSError, ValueError):
        return
    if user_dir in target.parents and target.is_file():
        _delete_file_silently(target)
