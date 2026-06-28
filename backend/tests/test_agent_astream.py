"""Tests para ``agent_loop_astream``: el loop async con eventos enriquecidos.

Mockeamos ``GoClient.astream`` (no la red) y verificamos que la versión
async del agent_loop yield-ea los eventos en el orden y con los campos
esperados:

  - ``phase`` antes de cada iteración del LLM
  - ``tool_call`` con ``description`` y ``display_args``
  - ``tool_result`` con ``duration_ms`` y ``description``
  - ``token`` por cada fragmento
  - ``final`` al cerrar

También verificamos que ``agent_loop_astream`` no bloquea el event loop
(``await`` al menos una vez durante la iteración).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.agent.nodes import agent_loop as agent_loop_mod
from app.agent.state import AgentState
from app.agent.tools.context import ToolContext
from app.agent.tools.registry import REGISTRY


# ── Fixtures ──────────────────────────────────────────────────
def _fake_tool_call(id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": id,
        "name": name,
        "arguments": args,
        "arguments_raw": json.dumps(args),
    }


def _chunk(delta_content: str = "", tool_calls: list | None = None) -> tuple:
    """Helper para armar un chunk en el shape de GoClient.astream."""
    return (delta_content, "deepseek-v4-flash", tool_calls or [])


@pytest.fixture
def fake_state() -> AgentState:
    return AgentState(
        user_id=1,
        chat_id=1,
        materia_id=1,
        materia_name="Sistemas Operativos",
        materia_year=3,
        modulo_id=1,
        modulo_name="TP1",
        model="deepseek-v4-flash",
        history=[],
        current_content="resumime el tp",
        career="Ing. en Sistemas",
        user_preferences={},
    )


@pytest.fixture
def fake_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    def _list_documents(ctx: ToolContext, modulo_id: int | None = None) -> dict[str, Any]:
        return {
            "ok": True,
            "tool": "list_documents",
            "documents": [
                {"id": 10, "filename": "enunciado.pdf", "status": "ready", "size": 5000},
            ],
            "count": 1,
        }

    def _read_document(
        ctx: ToolContext, document_id: int, max_chars: int | None = None
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "tool": "read_document",
            "document_id": document_id,
            "filename": "enunciado.pdf",
            "text": "Enunciado: implementar un shell básico.",
            "chunks_total": 1,
            "total_chars": 42,
            "returned_chars": 42,
            "truncated": False,
        }

    monkeypatch.setitem(
        REGISTRY,
        "list_documents",
        REGISTRY["list_documents"].__class__(
            name="list_documents",
            description=REGISTRY["list_documents"].description,
            fn=_list_documents,
            args_schema=REGISTRY["list_documents"].args_schema,
        ),
    )
    monkeypatch.setitem(
        REGISTRY,
        "read_document",
        REGISTRY["read_document"].__class__(
            name="read_document",
            description=REGISTRY["read_document"].description,
            fn=_read_document,
            args_schema=REGISTRY["read_document"].args_schema,
        ),
    )


# ── Tests ─────────────────────────────────────────────────────
async def test_agent_loop_astream_text_only(monkeypatch: pytest.MonkeyPatch,
                                              fake_state: AgentState) -> None:
    """LLM responde texto sin tools → events: phase, token*, final."""

    async def fake_astream(self: Any, **_kwargs: Any) -> Any:
        yield _chunk("Hola ")
        await asyncio.sleep(0)
        yield _chunk("mundo")
        await asyncio.sleep(0)
        # No tool_calls → cierra
        yield _chunk("", [])

    monkeypatch.setattr("app.agent.llm.GoClient.astream", fake_astream)

    events = [ev async for ev in agent_loop_mod.agent_loop_astream(fake_state)]

    kinds = [e["event"] for e in events]
    assert kinds[0] == "phase"
    assert "token" in kinds
    assert kinds[-1] == "final"
    # El phase inicial debe ser "thinking"
    assert events[0]["phase"] == "thinking"
    # Los tokens acumulan el texto final
    final = next(e for e in events if e["event"] == "final")
    assert "Hola mundo" in final["text"]
    assert final["iterations"] == 1
    assert final["tools_used"] == []


async def test_agent_loop_astream_with_tool_call(
    monkeypatch: pytest.MonkeyPatch,
    fake_state: AgentState,
    fake_documents: None,
) -> None:
    """LLM llama a list_documents → tool_result → respuesta final."""

    call_count = {"n": 0}

    async def fake_astream(self: Any, **_kwargs: Any) -> Any:
        call_count["n"] += 1
        if call_count["n"] == 1:
            yield _chunk("", [_fake_tool_call("call_1", "list_documents", {})])
        else:
            yield _chunk("Encontré 1 doc: enunciado.pdf.")

    monkeypatch.setattr("app.agent.llm.GoClient.astream", fake_astream)

    events = [ev async for ev in agent_loop_mod.agent_loop_astream(fake_state)]
    kinds = [e["event"] for e in events]

    # Orden esperado: phase → tool_call → tool_result → phase → token* → final
    assert kinds[0] == "phase"
    tool_call_idx = kinds.index("tool_call")
    tool_result_idx = kinds.index("tool_result")
    assert tool_call_idx < tool_result_idx
    assert kinds[tool_result_idx + 1] == "phase"  # nueva iteración
    final_idx = kinds.index("final")
    assert tool_result_idx < final_idx

    # tool_call viene con description y display_args
    tc = events[tool_call_idx]
    assert tc["name"] == "list_documents"
    assert "description" in tc
    assert "Listando" in tc["description"]
    assert "display_args" in tc

    # tool_result viene con duration_ms y description
    tr = events[tool_result_idx]
    assert tr["tool"] == "list_documents"
    assert tr["ok"] is True
    assert tr["duration_ms"] >= 0
    assert "description" in tr

    final = events[final_idx]
    assert "enunciado" in final["text"]
    assert final["tools_used"] == ["list_documents"]
    assert final["iterations"] == 2


async def test_agent_loop_astream_emits_phase_with_tools(
    monkeypatch: pytest.MonkeyPatch,
    fake_state: AgentState,
    fake_documents: None,
) -> None:
    """Después de la primera tool_call, el phase siguiente debe ser 'tools'."""

    call_count = {"n": 0}

    async def fake_astream(self: Any, **_kwargs: Any) -> Any:
        call_count["n"] += 1
        if call_count["n"] == 1:
            yield _chunk("", [_fake_tool_call("call_x", "list_documents", {})])
        else:
            yield _chunk("listo")

    monkeypatch.setattr("app.agent.llm.GoClient.astream", fake_astream)

    events = [ev async for ev in agent_loop_mod.agent_loop_astream(fake_state)]
    phases = [e for e in events if e["event"] == "phase"]
    # El primero siempre es "thinking"; los siguientes también hasta que
    # haya tool_calls → "tools" en la 2da iteración
    assert phases[0]["phase"] == "thinking"
    assert any(p["phase"] == "tools" for p in phases)


async def test_agent_loop_astream_does_not_block_event_loop(
    monkeypatch: pytest.MonkeyPatch,
    fake_state: AgentState,
) -> None:
    """Mientras el LLM 'duerme', otras corutinas deben poder correr."""

    sleeper_ran = {"v": False}

    async def fake_astream(self: Any, **_kwargs: Any) -> Any:
        yield _chunk("a")
        await asyncio.sleep(0.02)
        yield _chunk("b")

    async def other_coro() -> None:
        await asyncio.sleep(0.01)
        sleeper_ran["v"] = True

    monkeypatch.setattr("app.agent.llm.GoClient.astream", fake_astream)

    async def runner() -> None:
        async for _ in agent_loop_mod.agent_loop_astream(fake_state):
            pass

    await asyncio.gather(runner(), other_coro())
    assert sleeper_ran["v"] is True


async def test_agent_loop_astream_token_deltas_accumulate(
    monkeypatch: pytest.MonkeyPatch,
    fake_state: AgentState,
) -> None:
    """Varios deltas pequeños deben aparecer como tokens separados."""
    pieces = [f"p{i}" for i in range(5)]

    async def fake_astream(self: Any, **_kwargs: Any) -> Any:
        for p in pieces:
            yield _chunk(p)
            await asyncio.sleep(0)

    monkeypatch.setattr("app.agent.llm.GoClient.astream", fake_astream)

    events = [ev async for ev in agent_loop_mod.agent_loop_astream(fake_state)]
    token_texts = [e["text"] for e in events if e["event"] == "token"]
    assert token_texts == pieces


async def test_agent_loop_astream_emits_llm_call_and_response(
    monkeypatch: pytest.MonkeyPatch,
    fake_state: AgentState,
    fake_documents: None,
) -> None:
    """Cada iteración del LLM emite ``llm_call`` y ``llm_response``.

    Verifica:
      - En el orden correcto (después de ``phase``, antes de
        ``tool_call`` / ``token``).
      - Con los campos esperados (iteration, model, messages_count,
        total_chars para llm_call; finish_reason, text_chars,
        tool_calls_count, duration_ms para llm_response).
      - Que en una iteración con tool_call, ``finish_reason`` =
        ``"tool_calls"``, y en una iteración con texto,
        ``finish_reason`` = ``"stop"``.
    """
    call_count = {"n": 0}

    async def fake_astream(self: Any, **_kwargs: Any) -> Any:
        call_count["n"] += 1
        if call_count["n"] == 1:
            yield _chunk("", [_fake_tool_call("call_1", "list_documents", {})])
        else:
            yield _chunk("listo")

    monkeypatch.setattr("app.agent.llm.GoClient.astream", fake_astream)

    events = [ev async for ev in agent_loop_mod.agent_loop_astream(fake_state)]

    llm_call_events = [e for e in events if e.get("event") == "llm_call"]
    llm_response_events = [e for e in events if e.get("event") == "llm_response"]
    assert len(llm_call_events) == 2
    assert len(llm_response_events) == 2

    # Iteración 1: tool_calls → finish_reason="tool_calls"
    assert llm_response_events[0]["finish_reason"] == "tool_calls"
    assert llm_response_events[0]["tool_calls_count"] == 1
    assert llm_response_events[0]["text_chars"] == 0
    assert llm_response_events[0]["duration_ms"] >= 0

    # Iteración 2: texto → finish_reason="stop"
    assert llm_response_events[1]["finish_reason"] == "stop"
    assert llm_response_events[1]["tool_calls_count"] == 0
    assert llm_response_events[1]["text_chars"] == len("listo")

    # ``llm_call`` tiene los metadatos del request
    for ev in llm_call_events:
        assert ev["iteration"] >= 1
        assert ev["model"] == "deepseek-v4-flash"
        assert ev["messages_count"] >= 1
        assert ev["total_chars"] >= 0

    # Orden: en cada iteración, llm_call viene DESPUÉS de phase y ANTES
    # de tool_call/token/tool_result; llm_response viene DESPUÉS de los
    # tokens/tool_calls de esa iteración.
    phase_idx = next(i for i, e in enumerate(events) if e["event"] == "phase")
    first_llm_call_idx = next(i for i, e in enumerate(events) if e["event"] == "llm_call")
    first_tool_call_idx = next(i for i, e in enumerate(events) if e["event"] == "tool_call")
    first_llm_response_idx = next(
        i for i, e in enumerate(events) if e["event"] == "llm_response"
    )
    first_tool_result_idx = next(
        i for i, e in enumerate(events) if e["event"] == "tool_result"
    )
    assert phase_idx < first_llm_call_idx < first_tool_call_idx < first_llm_response_idx
    assert first_llm_response_idx < first_tool_result_idx
