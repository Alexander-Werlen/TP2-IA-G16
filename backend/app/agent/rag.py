"""RAG: indexado y búsqueda semántica en ChromaDB (Fase 5).

Arquitectura:
  - Una sola colección: ``tutoria_documents``.
  - Filtros por ``materia_id`` y ``user_id`` en metadata para aislar
    retrieval por materia y por usuario (defensa en profundidad).
  - Embeddings vía ``gemini-embedding-2`` usando el SDK ``google-genai``.
  - Cliente Chroma HTTP (v2 API) contra el servicio del compose.

API expuesta:
  - ``index_document_chunks(...)``  indexa los chunks de un documento.
  - ``delete_document_chunks(document_id)``  borra los chunks de un doc.
  - ``has_indexed_documents(materia_id, user_id)``  ¿hay algo indexado?
  - ``search(query, materia_id, user_id, k)``  recupera los top-k chunks.
  - ``format_context(chunks)``  formatea los chunks para inyectar en el
    system_instruction, incluyendo el formato de cita ``[doc:…, chunk:N]``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from google import genai
from google.genai import errors as genai_errors

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

COLLECTION_NAME = "tutoria_documents"
EMBED_BATCH_SIZE = 32  # tamaño seguro para la API de embeddings de Gemini


def _materia_user_where(materia_id: int, user_id: int) -> dict:
    """Chroma v2 exige UN operador en ``where``; para combinar varios
    campos hay que usar ``$and``/``$or``. Esta función arma el filtro
    materia+user en el formato correcto.
    """
    return {
        "$and": [
            {"materia_id": materia_id},
            {"user_id": user_id},
        ]
    }


# ── Tipos públicos ──────────────────────────────────────────
@dataclass(frozen=True)
class RetrievedChunk:
    text: str
    filename: str
    chunk_index: int
    document_id: int
    score: float  # distancia (menor = más similar, cosine)


# ── Cliente Chroma (lazy) ───────────────────────────────────
_client = None
_collection = None


def _chroma_settings(settings: Settings) -> tuple[str, int]:
    return settings.chroma_host, settings.chroma_port


def _get_collection():
    """Devuelve la colección única de Chroma, creándola si no existe."""
    global _client, _collection
    if _collection is not None:
        return _collection

    import chromadb  # import diferido: paquete pesado

    settings = get_settings()
    host, port = _chroma_settings(settings)
    _client = chromadb.HttpClient(host=host, port=port)
    _collection = _client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    logger.info(
        "rag: Chroma conectado en %s:%s, colección=%s",
        host,
        port,
        COLLECTION_NAME,
    )
    return _collection


def reset_clients() -> None:
    """Para tests: descarta el cliente y la colección cacheados."""
    global _client, _collection
    _client = None
    _collection = None


# ── Embeddings ──────────────────────────────────────────────
def _get_genai_client() -> genai.Client:
    settings = get_settings()
    if not settings.google_api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY no está configurada. Definila en .env antes de "
            "usar RAG."
        )
    return genai.Client(api_key=settings.google_api_key)


def _embed_texts(texts: list[str], settings: Settings) -> list[list[float]]:
    """Embeddea una lista de textos en batches.

    Lanza ``RuntimeError`` si la API key no está configurada, o propaga
    ``google.genai.errors.APIError`` si la API falla.
    """
    client = _get_genai_client()
    model = settings.embedding_model

    out: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[start : start + EMBED_BATCH_SIZE]
        try:
            response = client.models.embed_content(model=model, contents=batch)
        except genai_errors.APIError:
            logger.exception("rag.embed: Gemini embed_content falló (batch_size=%d)", len(batch))
            raise
        for emb in response.embeddings:
            values = getattr(emb, "values", None)
            if values is None:
                raise RuntimeError("rag.embed: respuesta de Gemini sin .values")
            out.append(list(values))
    return out


# ── Indexado ────────────────────────────────────────────────
def index_document_chunks(
    *,
    document_id: int,
    modulo_id: int,
    materia_id: int,
    user_id: int,
    filename: str,
    chunks: list[str],
) -> int:
    """Indexa los chunks de un documento en Chroma. Devuelve la cantidad upserted.

    Si el documento ya tenía chunks indexados (por un re-run), los
    sobreescribe: usamos IDs deterministas ``d{document_id}-c{idx}``.
    """
    if not chunks:
        return 0
    settings = get_settings()
    collection = _get_collection()

    embeddings = _embed_texts(chunks, settings)
    ids = [f"d{document_id}-c{idx}" for idx in range(len(chunks))]
    metadatas = [
        {
            "document_id": document_id,
            "modulo_id": modulo_id,
            "materia_id": materia_id,
            "user_id": user_id,
            "filename": filename,
            "chunk_index": idx,
        }
        for idx in range(len(chunks))
    ]

    collection.upsert(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)
    logger.info(
        "rag.index document_id=%s materia_id=%s chunks=%d",
        document_id,
        materia_id,
        len(chunks),
    )
    return len(chunks)


# ── Borrado ─────────────────────────────────────────────────
def delete_document_chunks(document_id: int) -> None:
    """Borra todos los chunks de un documento de Chroma."""
    collection = _get_collection()
    collection.delete(where={"document_id": document_id})
    logger.info("rag.delete document_id=%s", document_id)


# ── Búsqueda ────────────────────────────────────────────────
def has_indexed_documents(*, materia_id: int, user_id: int) -> bool:
    """Chequeo barato: ¿hay al menos un chunk indexado en esta materia+user?

    Usa ``get`` con un ``limit=1`` en vez de ``count`` para no cargar
    todo el dataset. Es una heurística: si hay metadata stale podría
    devolver True sin que el retrieval encuentre nada útil, pero ese caso
    se maneja en ``search`` (devuelve lista vacía sin error).
    """
    try:
        collection = _get_collection()
    except Exception:  # noqa: BLE001
        logger.exception("rag.has_indexed: no se pudo conectar a Chroma")
        return False
    try:
        result = collection.get(
            where=_materia_user_where(materia_id, user_id),
            limit=1,
        )
    except Exception:  # noqa: BLE001
        logger.exception("rag.has_indexed: collection.get falló")
        return False
    ids = result.get("ids") or []
    return len(ids) > 0


def search(
    *,
    query: str,
    materia_id: int,
    user_id: int,
    k: int = 6,
) -> list[RetrievedChunk]:
    """Recupera los top-k chunks relevantes para ``query`` en la materia del user.

    Filtra server-side por ``materia_id`` y ``user_id`` para que un chat
    en otra materia no recupere chunks de esta.
    """
    if not query or not query.strip():
        return []
    settings = get_settings()
    collection = _get_collection()

    embeddings = _embed_texts([query], settings)
    result = collection.query(
        query_embeddings=embeddings,
        n_results=k,
        where=_materia_user_where(materia_id, user_id),
    )

    ids = (result.get("ids") or [[]])[0]
    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]

    out: list[RetrievedChunk] = []
    for i, text in enumerate(docs):
        meta = metas[i] if i < len(metas) else {}
        distance = distances[i] if i < len(distances) else 0.0
        out.append(
            RetrievedChunk(
                text=text,
                filename=str(meta.get("filename", "desconocido")),
                chunk_index=int(meta.get("chunk_index", 0)),
                document_id=int(meta.get("document_id", 0)),
                score=float(distance),
            )
        )
    logger.info(
        "rag.search materia_id=%s user_id=%s k=%d retrieved=%d",
        materia_id,
        user_id,
        k,
        len(out),
    )
    return out


# ── Formateo para el prompt ─────────────────────────────────
def format_context(chunks: list[RetrievedChunk]) -> str:
    """Arma el bloque de contexto a inyectar en el system_instruction.

    El formato de cita ``[doc:filename, chunk:N]`` es literal y se
    incluye en cada bloque para que el LLM lo repita tal cual en la
    respuesta.
    """
    if not chunks:
        return ""
    parts = [
        "Fragmentos relevantes de los apuntes del usuario (úsalos si "
        "responden la pregunta y citá la fuente entre corchetes al final "
        "de cada idea que uses, formato exacto [doc:filename, chunk:N]):",
        "",
    ]
    for c in chunks:
        citation = f"[doc:{c.filename}, chunk:{c.chunk_index}]"
        parts.append(citation)
        parts.append(c.text.strip())
        parts.append("")
    return "\n".join(parts).rstrip()
