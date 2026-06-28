"""Nodo ``agent_loop``: pipeline con function-calling nativo.

A partir de la migración a function-calling, este nodo único reemplaza
los antiguos ``perceive``, ``plan``, ``retrieve``, ``tools`` y ``answer``.
El LLM recibe la lista de tools disponibles y decide iterativamente
cuáles llamar; cada tool_call se ejecuta localmente y su resultado se
re-inyecta al LLM como un mensaje ``role: "tool"`` hasta que el LLM
emita una respuesta final (``finish_reason == "stop"``).

Cap de iteraciones duro: ``MAX_AGENT_ITERATIONS`` (default 5, definido
en ``app.agent.prompts``). Si el LLM no converge, devolvemos lo que
tengamos + un warning en el log.

Hay dos variantes del loop:
  - ``agent_loop`` / ``agent_loop_stream``: versiones sync (testeas y
    compatibilidad con el grafo LangGraph, que las prefiere sync).
  - ``agent_loop_astream``: versión async que usa ``AsyncOpenAI`` y
    ``await`` para no bloquear el event loop. Es la que consume el
    endpoint SSE de FastAPI (``/chats/{id}/messages/stream``) para que
    cada token llegue al cliente en cuanto el LLM lo emite.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

from app.agent.llm import GoClient
from app.agent.prompts import (
    MAX_AGENT_ITERATIONS,
    build_system_instruction,
    summarize_tool_summaries,
)
from app.agent.state import AgentState
from app.agent.tools.context import ToolContext
from app.agent.tools.registry import REGISTRY, all_specs
from app.config import get_settings

logger = logging.getLogger(__name__)


def _build_context(state: AgentState) -> ToolContext:
    return ToolContext(
        user_id=state.get("user_id", 0),
        materia_id=state.get("materia_id"),
        materia_name=state.get("materia_name", ""),
        modulo_name=state.get("modulo_name", ""),
        chat_id=state.get("chat_id", 0),
    )


def _build_history(state: AgentState) -> list[dict[str, Any]]:
    """Arma la lista de mensajes user/assistant a partir del estado."""
    messages: list[dict[str, Any]] = []
    for msg in state.get("history") or []:
        role = "assistant" if msg["role"] == "assistant" else "user"
        messages.append({"role": role, "content": msg["content"]})
    messages.append({"role": "user", "content": state.get("current_content", "")})
    return messages


def _tool_summaries() -> list[str]:
    """Lista corta ``"nombre → descripción"`` para el system prompt."""
    pairs = [(spec.name, spec.description) for spec in all_specs()]
    return summarize_tool_summaries(pairs)


def _build_system(state: AgentState) -> str:
    base = build_system_instruction(
        career=state.get("career") or "Ing. en Sistemas",
        year=state.get("materia_year") or 0,
        materia=state.get("materia_name") or "(sin materia)",
        modulo=state.get("modulo_name") or "(sin módulo)",
        tool_summaries=_tool_summaries(),
    )
    prefs = state.get("user_preferences") or {}
    if prefs:
        base += "\n\nPreferencias conocidas del estudiante: " + json.dumps(
            prefs, ensure_ascii=False
        ) + " (respetalas si entran en conflicto con el pedido)."
    return base


def _call_tool(
    ctx: ToolContext, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    spec = REGISTRY.get(name)
    if spec is None:
        return {"ok": False, "tool": name, "error": f"tool desconocida: {name}"}
    try:
        result = spec.fn(ctx, **arguments)
    except Exception as exc:  # noqa: BLE001
        logger.exception("agent_loop: tool %s explotó", name)
        return {"ok": False, "tool": name, "error": f"{exc.__class__.__name__}: {exc}"}
    if not isinstance(result, dict):
        return {"ok": False, "tool": name, "error": "tool no devolvió dict"}
    result.setdefault("tool", name)
    return result


def _tool_result_to_message(
    tool_call_id: str, result: dict[str, Any]
) -> dict[str, Any]:
    """Convierte un tool_result dict a un mensaje ``role: tool`` para OpenAI.

    No truncamos: dejamos que la API de OpenAI rechace con error si el
    resultado excede el context window. Eso le da al LLM visibilidad
    completa del tool result (importante para ``read_document``).
    """
    payload = {k: v for k, v in result.items() if k != "tool"}
    if not payload.get("ok") and "error" in payload:
        content_str = f"ERROR: {payload['error']}"
    else:
        try:
            content_str = json.dumps(payload, ensure_ascii=False, default=str)
        except TypeError:
            content_str = str(payload)
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content_str}


def _is_context_length_error(exc: BaseException) -> bool:
    """Detecta si la excepción de OpenAI es por context window excedido."""
    from openai import BadRequestError  # import local para no romper top-level

    if not isinstance(exc, BadRequestError):
        return False
    code = getattr(exc, "code", None)
    if code == "context_length_exceeded":
        return True
    # Fallback: revisar el body y el mensaje por si el code no está.
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error") or {}
        if err.get("code") == "context_length_exceeded":
            return True
        if err.get("type") == "context_length_exceeded":
            return True
    return "context_length_exceeded" in str(exc).lower() or (
        "maximum context length" in str(exc).lower()
    )


_CONTEXT_LENGTH_MSG = (
    "El documento o el contexto acumulado es demasiado largo para el modelo. "
    "Probá: (1) leer el documento en partes con max_chars más chico, "
    "(2) limpiar el historial del chat, "
    "(3) subir un documento más corto o dividirlo en varios."
)


def _assistant_message_with_tool_calls(
    tool_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    """Arma el assistant message con tool_calls para re-inyectar al LLM."""
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": tc.get("arguments_raw")
                    or json.dumps(tc.get("arguments") or {}),
                },
            }
            for tc in tool_calls
        ],
    }


def _summarize_for_log(result: dict[str, Any]) -> dict[str, Any]:
    """Resumen del tool_result sin pegar payloads enormes en logs."""
    text = result.get("text")
    if isinstance(text, str) and len(text) > 120:
        return {**result, "text": f"<{len(text)} chars>"}
    chunks = result.get("chunks")
    if isinstance(chunks, list) and len(chunks) > 3:
        return {**result, "chunks": f"<{len(chunks)} chunks>"}
    return result


def _conversation_chars(messages: list[dict[str, Any]]) -> int:
    """Suma los chars de los ``content`` de los mensajes (para el log)."""
    total = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            total += len(content)
    return total


def _run_loop_with_messages(
    *,
    client: GoClient,
    model: str,
    messages: list[dict[str, Any]],
    tools_payload: list[dict[str, Any]],
    tool_executor: Callable[[str, dict[str, Any]], dict[str, Any]],
    stream: bool = False,
    on_token: Callable[[str], None] | None = None,
) -> tuple[str, str, list[str], int, list[dict[str, Any]]]:
    """Loop completo: itera el LLM con function-calling hasta converger.

    Si ``stream=True``, usa ``client.stream()`` y llama a ``on_token`` por
    cada delta de texto. Si no, usa ``client.complete()`` (no-stream).

    Devuelve ``(final_text, used_model, tools_used, iterations, log)``.
    """
    conv: list[dict[str, Any]] = list(messages)
    tools_used: list[str] = []
    log: list[dict[str, Any]] = []
    iterations = 0
    final_text = ""
    used_model = model

    for iteration in range(1, MAX_AGENT_ITERATIONS + 1):
        iterations = iteration
        if stream:
            tool_calls_acc: list[dict[str, Any]] = []
            log.append(
                {
                    "kind": "llm_call",
                    "iteration": iteration,
                    "model": model,
                    "messages_count": len(conv),
                    "total_chars": _conversation_chars(conv),
                }
            )
            llm_t0 = time.perf_counter()
            try:
                stream_iter = client.stream(
                    history=[],
                    current_content="",
                    system_instruction="",  # ya viene en messages
                    model=model,
                    tools=tools_payload,
                    tool_choice="auto",
                    messages=conv,
                )
                for delta, used, tool_calls in stream_iter:
                    if used:
                        used_model = used
                    if delta:
                        if on_token is not None:
                            on_token(delta)
                    if tool_calls:
                        tool_calls_acc = tool_calls
            except Exception as exc:  # noqa: BLE001
                if _is_context_length_error(exc):
                    logger.warning(
                        "agent_loop: context length exceeded en iter %d", iteration,
                    )
                    return (_CONTEXT_LENGTH_MSG, used_model, tools_used, iteration, log)
                logger.exception("agent_loop: LLM stream falló en iter %d", iteration)
                return (
                    f"[error del LLM: {exc.__class__.__name__}]",
                    used_model,
                    tools_used,
                    iteration,
                    log,
                )

            # ``text_chars`` se cuenta por la diferencia de longitud del
            # ``accumulated`` del caller, pero como acá no lo tenemos,
            # lo dejamos en 0 y el caller (agent_loop_stream) lo completa.
            log.append(
                {
                    "kind": "llm_response",
                    "iteration": iteration,
                    "model": used_model,
                    "finish_reason": "tool_calls" if tool_calls_acc else "stop",
                    "text_chars": 0,
                    "tool_calls_count": len(tool_calls_acc),
                    "duration_ms": int((time.perf_counter() - llm_t0) * 1000),
                }
            )

            if not tool_calls_acc:
                # El LLM respondió texto: el caller ya acumuló con on_token,
                # pero necesitamos devolver el final_text también. Acá lo
                # estimamos a partir del último mensaje assistant.
                for m in reversed(conv):
                    if m.get("role") == "assistant" and m.get("content"):
                        final_text = m["content"]
                        break
                if not final_text:
                    # Si no hubo assistant previo, agarramos el delta del stream.
                    final_text = ""
                break

            # Appendear assistant + tool messages al conv.
            conv.append(_assistant_message_with_tool_calls(tool_calls_acc))
            for tc in tool_calls_acc:
                result = tool_executor(tc["name"], tc.get("arguments") or {})
                if tc["name"] not in tools_used:
                    tools_used.append(tc["name"])
                log.append(
                    {
                        "kind": "tool_call",
                        "iteration": iteration,
                        "tool": tc["name"],
                        "args": tc.get("arguments") or {},
                        "ok": result.get("ok", False),
                        "error": result.get("error") if not result.get("ok") else None,
                    }
                )
                conv.append(_tool_result_to_message(tc["id"], result))
            continue

        # No-stream
        log.append(
            {
                "kind": "llm_call",
                "iteration": iteration,
                "model": model,
                "messages_count": len(conv),
                "total_chars": _conversation_chars(conv),
            }
        )
        llm_t0 = time.perf_counter()
        try:
            result = client.complete(
                history=[],
                current_content="",
                system_instruction="",
                model=model,
                tools=tools_payload,
                tool_choice="auto",
                messages=conv,
            )
        except Exception as exc:  # noqa: BLE001
            if _is_context_length_error(exc):
                logger.warning(
                    "agent_loop: context length exceeded en iter %d", iteration,
                )
                return (_CONTEXT_LENGTH_MSG, used_model, tools_used, iteration, log)
            logger.exception("agent_loop: LLM falló en iter %d", iteration)
            return (
                f"[error del LLM: {exc.__class__.__name__}]",
                used_model,
                tools_used,
                iteration,
                log,
            )

        used_model = result.model
        log.append(
            {
                "kind": "llm_response",
                "iteration": iteration,
                "model": used_model,
                "finish_reason": "tool_calls" if result.tool_calls else "stop",
                "text_chars": len(result.text),
                "tool_calls_count": len(result.tool_calls),
                "duration_ms": int((time.perf_counter() - llm_t0) * 1000),
            }
        )

        if not result.tool_calls:
            final_text = result.text
            break

        # Appendear assistant + tool messages.
        conv.append(_assistant_message_with_tool_calls(result.tool_calls))
        for tc in result.tool_calls:
            tool_result = tool_executor(tc["name"], tc.get("arguments") or {})
            if tc["name"] not in tools_used:
                tools_used.append(tc["name"])
            log.append(
                {
                    "kind": "tool_call",
                    "iteration": iteration,
                    "tool": tc["name"],
                    "args": tc.get("arguments") or {},
                    "ok": tool_result.get("ok", False),
                    "error": tool_result.get("error") if not tool_result.get("ok") else None,
                }
            )
            conv.append(_tool_result_to_message(tc["id"], tool_result))

    return final_text, used_model, tools_used, iterations, log


# ── API no-stream ───────────────────────────────────────────────
def agent_loop(state: AgentState) -> AgentState:
    """Versión no-stream: ejecuta el loop completo y devuelve el estado final."""
    settings = get_settings()
    model = state.get("model") or settings.default_model
    client = GoClient(settings)
    ctx = _build_context(state)
    system = _build_system(state)
    history = _build_history(state)
    tools_payload = [spec.to_openai_schema() for spec in all_specs()]
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}, *history]

    def executor(name: str, args: dict[str, Any]) -> dict[str, Any]:
        return _call_tool(ctx, name, args)

    final_text, used_model, tools_used, iterations, log = _run_loop_with_messages(
        client=client,
        model=model,
        messages=messages,
        tools_payload=tools_payload,
        tool_executor=executor,
        stream=False,
    )
    return {
        "final_text": final_text,
        "tools_used": tools_used,
        "iterations": iterations,
        "tool_calls_log": log,
    }


# ── API streaming ───────────────────────────────────────────────
def agent_loop_stream(
    state: AgentState,
) -> Iterator[dict[str, Any]]:
    """Variante streaming del agent loop.

    Yield-ea dicts de eventos:
      - ``{"event": "phase", "phase": "thinking"|"tools"}`` antes de cada
        iteración del LLM.
      - ``{"event": "llm_call", "iteration", "model", "messages_count",
        "total_chars"}`` cuando arranca la llamada al LLM.
      - ``{"event": "token", "text": "..."}`` por cada fragmento.
      - ``{"event": "tool_call", "id", "name", "arguments"}`` cuando el
        LLM decide llamar una tool.
      - ``{"event": "llm_response", "iteration", "model",
        "finish_reason", "text_chars", "tool_calls_count",
        "duration_ms"}`` al cerrar la respuesta del LLM.
      - ``{"event": "tool_result", "tool", "ok", "summary"}`` al
        terminar la tool.
      - ``{"event": "final", "text", "model", "iterations", ...}`` al
        cerrar.
    """
    settings = get_settings()
    model = state.get("model") or settings.default_model
    client = GoClient(settings)
    ctx = _build_context(state)
    system = _build_system(state)
    history = _build_history(state)
    tools_payload = [spec.to_openai_schema() for spec in all_specs()]
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}, *history]

    accumulated = ""
    used_model = model
    tools_used: list[str] = []
    log: list[dict[str, Any]] = []
    iterations = 0

    def on_token(delta: str) -> None:
        nonlocal accumulated
        accumulated += delta

    def executor(name: str, args: dict[str, Any]) -> dict[str, Any]:
        return _call_tool(ctx, name, args)

    # En vez de hacer un loop aparte acá, manejamos los eventos de
    # tool_call / tool_result en un wrapper alrededor del executor: el
    # caller necesita ver qué tools se ejecutan. Para mantener simple la
    # separación, hacemos el loop manualmente con eventos.

    conv: list[dict[str, Any]] = list(messages)

    for iteration in range(1, MAX_AGENT_ITERATIONS + 1):
        iterations = iteration
        tool_calls_acc: list[dict[str, Any]] = []

        # Avisamos al frontend qué está por hacer el agente. El phase
        # es ``thinking`` la primera vez; si ya hubo tool_calls antes,
        # pasamos a ``tools`` (seguimos ejecutando tools). Cuando el LLM
        # empieza a producir texto, el frontend lo detecta por la llegada
        # del primer ``token`` y muestra "Respondiendo…".
        phase = "tools" if tools_used else "thinking"
        yield {"event": "phase", "phase": phase}

        prev_acc_len = len(accumulated)
        yield {
            "event": "llm_call",
            "iteration": iteration,
            "model": model,
            "messages_count": len(conv),
            "total_chars": _conversation_chars(conv),
        }
        llm_t0 = time.perf_counter()

        try:
            stream_iter = client.stream(
                history=[],
                current_content="",
                system_instruction="",
                model=model,
                tools=tools_payload,
                tool_choice="auto",
                messages=conv,
            )
            for delta, used, tool_calls in stream_iter:
                if used:
                    used_model = used
                if delta:
                    accumulated += delta
                    yield {"event": "token", "text": delta}
                if tool_calls:
                    tool_calls_acc = tool_calls
                    for tc in tool_calls_acc:
                        args = tc.get("arguments") or {}
                        yield {
                            "event": "tool_call",
                            "id": tc["id"],
                            "name": tc["name"],
                            "arguments": args,
                            "description": describe_tool_call(tc["name"], args),
                            "display_args": safe_display_args(tc["name"], args),
                        }
        except Exception as exc:  # noqa: BLE001
            if _is_context_length_error(exc):
                logger.warning(
                    "agent_loop_stream: context length exceeded en iter %d", iteration,
                )
                yield {"event": "error", "message": _CONTEXT_LENGTH_MSG, "code": "context_length_exceeded"}
                return
            logger.exception("agent_loop_stream: stream falló")
            yield {"event": "error", "message": f"LLM stream error: {exc.__class__.__name__}"}
            return

        yield {
            "event": "llm_response",
            "iteration": iteration,
            "model": used_model,
            "finish_reason": "tool_calls" if tool_calls_acc else "stop",
            "text_chars": len(accumulated) - prev_acc_len,
            "tool_calls_count": len(tool_calls_acc),
            "duration_ms": int((time.perf_counter() - llm_t0) * 1000),
        }

        if not tool_calls_acc:
            yield {
                "event": "final",
                "text": accumulated,
                "model": used_model,
                "iterations": iterations,
                "tools_used": tools_used,
                "tool_calls_log": log,
            }
            return

        # Appendear assistant + tool messages al conv.
        conv.append(_assistant_message_with_tool_calls(tool_calls_acc))
        for tc in tool_calls_acc:
            args = tc.get("arguments") or {}
            t0 = time.perf_counter()
            tool_result = _call_tool(ctx, tc["name"], args)
            duration_ms = int((time.perf_counter() - t0) * 1000)
            if tc["name"] not in tools_used:
                tools_used.append(tc["name"])
            log.append(
                {
                    "kind": "tool_call",
                    "iteration": iteration,
                    "tool": tc["name"],
                    "args": args,
                    "ok": tool_result.get("ok", False),
                    "error": tool_result.get("error") if not tool_result.get("ok") else None,
                }
            )
            yield {
                "event": "tool_result",
                "tool": tc["name"],
                "ok": tool_result.get("ok", False),
                "summary": _summarize_for_log(tool_result),
                "duration_ms": duration_ms,
                "description": describe_tool_call(
                    tc["name"], args, result_summary=tool_result
                ),
            }
            conv.append(_tool_result_to_message(tc["id"], tool_result))

    logger.warning(
        "agent_loop_stream: alcanzó MAX_AGENT_ITERATIONS=%d sin respuesta final; tools_used=%s",
        MAX_AGENT_ITERATIONS,
        tools_used,
    )
    yield {
        "event": "final",
        "text": accumulated,
        "model": used_model,
        "iterations": iterations,
        "tools_used": tools_used,
        "tool_calls_log": log,
        "warning": "max_iterations_reached",
    }


# ── API streaming async (la que usa el endpoint SSE) ──────────
async def agent_loop_astream(
    state: AgentState,
) -> AsyncIterator[dict[str, Any]]:
    """Versión async de :func:`agent_loop_stream`.

    Mismos eventos (``phase`` / ``llm_call`` / ``token`` / ``tool_call``
    / ``llm_response`` / ``tool_result`` / ``final`` / ``error``), pero
    cada iteración del LLM usa ``client.astream()`` que ``await``-ea
    los chunks. Esto evita bloquear el event loop de asyncio, así que
    el ``yield`` de cada ``sse_format(...)`` llega al cliente apenas el
    LLM emite el delta.
    """
    settings = get_settings()
    model = state.get("model") or settings.default_model
    client = GoClient(settings)
    ctx = _build_context(state)
    system = _build_system(state)
    history = _build_history(state)
    tools_payload = [spec.to_openai_schema() for spec in all_specs()]
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}, *history]

    accumulated = ""
    used_model = model
    tools_used: list[str] = []
    log: list[dict[str, Any]] = []
    iterations = 0

    conv: list[dict[str, Any]] = list(messages)

    for iteration in range(1, MAX_AGENT_ITERATIONS + 1):
        iterations = iteration
        tool_calls_acc: list[dict[str, Any]] = []

        phase = "tools" if tools_used else "thinking"
        yield {"event": "phase", "phase": phase}

        prev_acc_len = len(accumulated)
        yield {
            "event": "llm_call",
            "iteration": iteration,
            "model": model,
            "messages_count": len(conv),
            "total_chars": _conversation_chars(conv),
        }
        llm_t0 = time.perf_counter()

        try:
            stream_iter = client.astream(
                history=[],
                current_content="",
                system_instruction="",
                model=model,
                tools=tools_payload,
                tool_choice="auto",
                messages=conv,
            )
            async for delta, used, tool_calls in stream_iter:
                if used:
                    used_model = used
                if delta:
                    accumulated += delta
                    yield {"event": "token", "text": delta}
                if tool_calls:
                    tool_calls_acc = tool_calls
                    for tc in tool_calls_acc:
                        args = tc.get("arguments") or {}
                        yield {
                            "event": "tool_call",
                            "id": tc["id"],
                            "name": tc["name"],
                            "arguments": args,
                            "description": describe_tool_call(tc["name"], args),
                            "display_args": safe_display_args(tc["name"], args),
                        }
        except Exception as exc:  # noqa: BLE001
            if _is_context_length_error(exc):
                logger.warning(
                    "agent_loop_astream: context length exceeded en iter %d", iteration,
                )
                yield {
                    "event": "error",
                    "message": _CONTEXT_LENGTH_MSG,
                    "code": "context_length_exceeded",
                }
                return
            logger.exception("agent_loop_astream: stream falló")
            yield {
                "event": "error",
                "message": f"LLM stream error: {exc.__class__.__name__}",
            }
            return

        yield {
            "event": "llm_response",
            "iteration": iteration,
            "model": used_model,
            "finish_reason": "tool_calls" if tool_calls_acc else "stop",
            "text_chars": len(accumulated) - prev_acc_len,
            "tool_calls_count": len(tool_calls_acc),
            "duration_ms": int((time.perf_counter() - llm_t0) * 1000),
        }

        if not tool_calls_acc:
            yield {
                "event": "final",
                "text": accumulated,
                "model": used_model,
                "iterations": iterations,
                "tools_used": tools_used,
                "tool_calls_log": log,
            }
            return

        # Appendear assistant + tool messages al conv.
        conv.append(_assistant_message_with_tool_calls(tool_calls_acc))
        for tc in tool_calls_acc:
            args = tc.get("arguments") or {}
            t0 = time.perf_counter()
            tool_result = _call_tool(ctx, tc["name"], args)
            duration_ms = int((time.perf_counter() - t0) * 1000)
            if tc["name"] not in tools_used:
                tools_used.append(tc["name"])
            log.append(
                {
                    "kind": "tool_call",
                    "iteration": iteration,
                    "tool": tc["name"],
                    "args": args,
                    "ok": tool_result.get("ok", False),
                    "error": tool_result.get("error") if not tool_result.get("ok") else None,
                }
            )
            yield {
                "event": "tool_result",
                "tool": tc["name"],
                "ok": tool_result.get("ok", False),
                "summary": _summarize_for_log(tool_result),
                "duration_ms": duration_ms,
                "description": describe_tool_call(
                    tc["name"], args, result_summary=tool_result
                ),
            }
            conv.append(_tool_result_to_message(tc["id"], tool_result))

    logger.warning(
        "agent_loop_astream: alcanzó MAX_AGENT_ITERATIONS=%d sin respuesta final; tools_used=%s",
        MAX_AGENT_ITERATIONS,
        tools_used,
    )
    yield {
        "event": "final",
        "text": accumulated,
        "model": used_model,
        "iterations": iterations,
        "tools_used": tools_used,
        "tool_calls_log": log,
        "warning": "max_iterations_reached",
    }


# ── Descripciones humanas de tool calls ───────────────────────
# Whitelist de keys seguras para mostrar en la UI. Cualquier otra key
# se descarta (no filtramos el contenido crudo al frontend).
_DISPLAY_KEYS: dict[str, tuple[str, ...]] = {
    "list_documents": ("modulo_id",),
    "read_document": ("document_id",),
    "rag_search": ("query", "k"),
    "get_user_memory": (),
    "update_user_memory": ("current_year",),
    "list_upcoming_events": ("from_", "to"),
    "set_event": ("type", "date", "description"),
    "summarize_document": ("document_id",),
}


def safe_display_args(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Filtra y formatea los args de un tool_call para mostrar en la UI.

    - Solo deja pasar las keys declaradas en ``_DISPLAY_KEYS`` para esa tool.
    - Trunca strings largos a 80 chars (con ``…``).
    - Devuelve un dict nuevo (no muta el original).
    """
    allowed = _DISPLAY_KEYS.get(name, ())
    out: dict[str, Any] = {}
    for key in allowed:
        if key not in args:
            continue
        val = args[key]
        if isinstance(val, str) and len(val) > 80:
            val = val[:79] + "…"
        out[key] = val
    return out


def describe_tool_call(
    name: str,
    args: dict[str, Any],
    *,
    result_summary: dict[str, Any] | None = None,
) -> str:
    """Devuelve una descripción humana en español de un tool_call.

    El frontend la muestra en el panel de "pasos" del streaming
    (ej. ``"Leyendo 'enunciado.pdf' (5 KB)…"``).

    ``result_summary`` (opcional) se usa para enriquecer la descripción
    con info del tool_result (ej. ``filename`` de ``read_document``,
    ``count`` de ``list_documents``).
    """
    a = args or {}
    if name == "list_documents":
        base = "Listando documentos del módulo"
        if a.get("modulo_id"):
            base = f"{base} #{a['modulo_id']}"
        if result_summary and "count" in result_summary:
            base = f"{base} ({result_summary['count']} encontrados)"
        return base
    if name == "read_document":
        base = f"Leyendo documento #{a.get('document_id', '?')}"
        if result_summary:
            fn = result_summary.get("filename")
            tc = result_summary.get("total_chars")
            if fn:
                base = f"Leyendo '{fn}'"
            if isinstance(tc, int) and tc > 0:
                base = f"{base} ({tc:,} chars)"
        return base
    if name == "rag_search":
        q = a.get("query", "")
        k = a.get("k")
        if k and k != 6:
            return f'Buscando: "{q}" ({k} chunks)'
        return f'Buscando: "{q}"'
    if name == "get_user_memory":
        return "Consultando tus preferencias"
    if name == "update_user_memory":
        if a.get("current_year") is not None:
            return f"Actualizando año actual a {a['current_year']}.º"
        return "Guardando preferencias"
    if name == "list_upcoming_events":
        return "Consultando tu agenda"
    if name == "set_event":
        type_label = {
            "parcial": "parcial",
            "recuperatorio": "recuperatorio",
            "final": "final",
            "entrega": "entrega",
            "exposicion": "exposición",
            "otro": "evento",
        }.get(a.get("type", ""), "evento")
        date = a.get("date", "")
        return f"Agendando {type_label} del {date}" if date else f"Agendando {type_label}"
    if name == "summarize_document":
        return f"Resumiendo documento #{a.get('document_id', '?')}"
    return name
