"""Document chunker (Fase 4).

Estrategia: split por párrafos (saltos de línea), mergea párrafos cortos
hasta ``max_chars`` y solapa ``overlap`` caracteres entre chunks
consecutivos para no romper ideas que crucen el corte.

Decisiones:
  - El texto ya viene normalizado por el parser (``\\n\\n`` separa párrafos).
  - No se pican palabras por la mitad para el overlap: el solapamiento se
    hace alineando a fronteras de palabra, retrocediendo del corte hasta
    el último espacio dentro de los últimos ``overlap`` chars.
  - ``overlap >= max_chars`` se trata como ``overlap = max_chars // 2``
    para no entrar en bucle.
  - Si el texto es muy corto (< max_chars) se devuelve un único chunk.
"""
from __future__ import annotations

MIN_CHARS = 30  # chunks más cortos que esto se descartan (ruido)


def chunk_text(
    text: str,
    max_chars: int = 1000,
    overlap: int = 200,
) -> list[str]:
    """Divide ``text`` en chunks de a lo sumo ``max_chars`` con overlap."""
    if not text or not text.strip():
        return []

    if max_chars <= 0:
        raise ValueError("max_chars debe ser > 0")
    if overlap < 0:
        raise ValueError("overlap debe ser >= 0")
    if overlap >= max_chars:
        overlap = max(0, max_chars // 2)

    paragraphs = _split_paragraphs(text)
    merged = _merge_paragraphs(paragraphs, max_chars=max_chars)
    if not merged:
        return []

    chunks = _apply_overlap(merged, max_chars=max_chars, overlap=overlap)
    return [c for c in chunks if len(c.strip()) >= MIN_CHARS]


def _split_paragraphs(text: str) -> list[str]:
    """Parte por saltos de línea. Cada párrafo es una 'idea'."""
    raw = text.split("\n")
    # Agrupar líneas consecutivas no vacías en el mismo párrafo.
    paragraphs: list[str] = []
    buffer: list[str] = []
    for line in raw:
        stripped = line.strip()
        if not stripped:
            if buffer:
                paragraphs.append(" ".join(buffer).strip())
                buffer = []
            continue
        buffer.append(stripped)
    if buffer:
        paragraphs.append(" ".join(buffer).strip())

    # Filtrar párrafos muy cortos (headers sueltos, líneas decorativas).
    return [p for p in paragraphs if len(p) >= MIN_CHARS]


def _merge_paragraphs(paragraphs: list[str], *, max_chars: int) -> list[str]:
    """Une párrafos hasta ``max_chars`` sin cortar a la mitad."""
    merged: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        # Si el párrafo solo no entra, lo guardamos igual y seguimos.
        added = len(para) + (2 if current else 0)  # "\n\n" entre joins
        if current_len + added > max_chars and current:
            merged.append("\n\n".join(current))
            current = [para]
            current_len = len(para)
        else:
            current.append(para)
            current_len += added

    if current:
        merged.append("\n\n".join(current))
    return merged


def _apply_overlap(blocks: list[str], *, max_chars: int, overlap: int) -> list[str]:
    """Toma ``blocks`` (ya dentro de max_chars) y agrega overlap entre ellas.

    El overlap se hace retrocediendo del final del bloque previo hasta el
    último espacio dentro de los últimos ``overlap`` caracteres, y
    prependiendo ese sufijo al inicio del bloque siguiente.
    """
    if len(blocks) == 1 or overlap == 0:
        return blocks

    out: list[str] = [blocks[0]]
    for i in range(1, len(blocks)):
        prev = blocks[i - 1]
        curr = blocks[i]
        if len(prev) <= overlap:
            tail = prev
        else:
            tail = _word_tail(prev, overlap)

        combined = (tail + "\n\n" + curr) if tail else curr
        # Si el overlap hace que combined supere max_chars, lo recortamos.
        if len(combined) > max_chars + overlap:
            combined = combined[: max_chars + overlap]
        out.append(combined.strip())
    return out


def _word_tail(text: str, max_len: int) -> str:
    """Devuelve los últimos ``max_len`` chars de ``text`` alineados a una
    frontera de palabra (no corta palabras a la mitad).
    """
    if len(text) <= max_len:
        return text
    candidate = text[-max_len:]
    # Buscar el primer espacio dentro de candidate; si no hay, devolver tal cual.
    space = candidate.find(" ")
    if space == -1 or space == len(candidate) - 1:
        return candidate
    return candidate[space + 1 :]
