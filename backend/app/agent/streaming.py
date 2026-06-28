"""Helpers para producir respuestas Server-Sent Events (SSE) en FastAPI.

Se mantiene deliberadamente pequeño y sin dependencias nuevas. El frontend
parsea los eventos con ``fetch`` + ``ReadableStream`` (ver ``api.ts``).

Convención de eventos emitidos por la Fase 3:

  event: meta
  data: {"user_message_id": N, "assistant_message_id": M, "model": "..."}

  event: token
  data: "<fragmento de texto>"

  event: done
  data: {"model": "...", "tokens_in": X, "tokens_out": Y}

  event: error
  data: "<mensaje>"
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi.responses import StreamingResponse


def sse_format(event: str, data: str) -> bytes:
    """Formatea un evento SSE en bytes UTF-8 terminados en ``\\n\\n``."""
    if "\n" in data and not data.startswith("{"):
        # data multilínea → cada línea se antepone con "data: ".
        lines = "\n".join(f"data: {ln}" for ln in data.splitlines())
        payload = f"event: {event}\n{lines}\n\n"
    else:
        payload = f"event: {event}\ndata: {data}\n\n"
    return payload.encode("utf-8")


def sse_format_json(event: str, payload: Any) -> bytes:
    """Atajo para serializar ``data`` como JSON."""
    return sse_format(event, json.dumps(payload, ensure_ascii=False))


def sse_response(generator: AsyncIterator[bytes]) -> StreamingResponse:
    """Envuelve un generador async de bytes como respuesta ``text/event-stream``."""
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # desactiva buffering en nginx si aparece
            "Connection": "keep-alive",
        },
    )
