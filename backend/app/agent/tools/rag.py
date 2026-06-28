"""RAG search tool (Fase 6).

Wrapper delgado de ``app.agent.rag.search`` que se ajusta al contrato
``ToolContext → ToolResult``.
"""
from __future__ import annotations

import logging

from app.agent import rag
from app.agent.tools.context import ToolContext, ToolResult, err, ok

logger = logging.getLogger(__name__)

NAME = "rag_search"


def run(query: str, ctx: ToolContext, k: int = 6) -> ToolResult:
    if not query or not query.strip():
        return err("query vacía")
    if ctx.materia_id is None:
        return err("sin materia_id en el contexto")
    try:
        chunks = rag.search(
            query=query.strip(),
            materia_id=ctx.materia_id,
            user_id=ctx.user_id,
            k=k,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("rag_search tool falló")
        return err(f"rag.search: {exc.__class__.__name__}")
    payload = [
        {
            "text": c.text,
            "filename": c.filename,
            "chunk_index": c.chunk_index,
            "document_id": c.document_id,
            "score": c.score,
        }
        for c in chunks
    ]
    logger.info("tool.rag_search user_id=%s materia_id=%s retrieved=%d", ctx.user_id, ctx.materia_id, len(payload))
    return ok(chunks=payload, count=len(payload))
