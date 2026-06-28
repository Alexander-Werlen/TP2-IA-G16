"""Document text extraction (Fase 4).

Soporta PDF (pypdf), DOCX (python-docx) y TXT plano. Despacha por MIME
declarado por el cliente; si la extensión no coincide, intenta inferir
por la firma (magic bytes) como fallback.
"""
from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)


# MIME aceptados y el parser que les corresponde.
MIME_PDF = "application/pdf"
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_TXT = "text/plain"

ACCEPTED_MIMES: tuple[str, ...] = (MIME_PDF, MIME_DOCX, MIME_TXT)


class ParserError(ValueError):
    """No se pudo extraer texto del documento."""


def is_accepted_mime(mime: str) -> bool:
    return mime in ACCEPTED_MIMES


def extract_text(filename: str, mime: str, content: bytes) -> str:
    """Devuelve el texto plano del documento.

    Lanza ``ParserError`` con un mensaje legible si el tipo no se puede
    procesar. Si el PDF/DOCX no contiene texto extraíble (escaneado,
    encriptado, etc.) también lanza ``ParserError``.
    """
    if not content:
        raise ParserError("El archivo está vacío")

    # Si el MIME no es uno de los aceptados, intentar deducir.
    resolved = mime or _guess_mime(filename, content)

    if resolved == MIME_PDF:
        text = _extract_pdf(content)
    elif resolved == MIME_DOCX:
        text = _extract_docx(content)
    elif resolved == MIME_TXT:
        text = _extract_txt(content)
    else:
        raise ParserError(
            f"Tipo de archivo no soportado: {mime or 'desconocido'}. "
            f"Aceptados: {', '.join(ACCEPTED_MIMES)}"
        )

    text = _normalize(text)
    if len(text.strip()) < 10:
        raise ParserError(
            "No se pudo extraer texto útil del documento "
            "(¿es un PDF escaneado o un DOCX sin texto?)"
        )
    return text


# ── parsers por tipo ────────────────────────────────────────
def _extract_pdf(content: bytes) -> str:
    from pypdf import PdfReader  # import diferido: pypdf es pesado

    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as err:  # noqa: BLE001
        raise ParserError(f"PDF inválido o encriptado: {err}") from err

    parts: list[str] = []
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception as err:  # noqa: BLE001
            logger.warning("PDF: página no se pudo extraer (%s)", err)
            continue
        if page_text:
            parts.append(page_text)
    return "\n\n".join(parts)


def _extract_docx(content: bytes) -> str:
    from docx import Document as DocxDocument  # python-docx

    try:
        doc = DocxDocument(io.BytesIO(content))
    except Exception as err:  # noqa: BLE001
        raise ParserError(f"DOCX inválido: {err}") from err

    parts: list[str] = []
    for para in doc.paragraphs:
        if para.text:
            parts.append(para.text)
    return "\n\n".join(parts)


def _extract_txt(content: bytes) -> str:
    # Probamos utf-8, después latin-1 como fallback.
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    # latin-1 nunca falla: si llegamos acá, igual devolvemos lo que haya.
    return content.decode("latin-1", errors="replace")


# ── helpers ────────────────────────────────────────────────
def _normalize(text: str) -> str:
    """Limpia whitespace excesivo y caracteres de control sin destruir saltos."""
    # Quitar carriage returns, dejar solo \n.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Colapsar 3+ saltos consecutivos a 2 (separador de párrafos).
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    # Quitar espacios al final de cada línea.
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def _guess_mime(filename: str, content: bytes) -> str:
    """Fallback si el cliente no envió un MIME reconocible."""
    name = (filename or "").lower()
    head = content[:8]
    if name.endswith(".pdf") or head.startswith(b"%PDF"):
        return MIME_PDF
    if name.endswith(".docx") or head.startswith(b"PK\x03\x04"):
        # ZIP-based; los .docx son zips. Si la extensión es .docx asumimos docx.
        if name.endswith(".docx"):
            return MIME_DOCX
    if name.endswith(".txt"):
        return MIME_TXT
    return ""
