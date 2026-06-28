"""Tests para el agent_loop con function-calling.

El test mockea el GoClient y simula un flujo donde el LLM:
  1. Decide llamar ``list_documents``.
  2. Recibe la lista y decide llamar ``read_document`` sobre dos
     documentos.
  3. Con los textos en contexto, emite la respuesta final.

Verifica que el loop itera, ejecuta las tools, y devuelve el texto
final correctamente.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.agent.nodes import agent_loop as agent_loop_mod
from app.agent.state import AgentState
from app.agent.tools.context import ToolContext
from app.agent.tools.registry import REGISTRY


# ── Fixtures ─────────────────────────────────────────────────────
class FakeToolCall:
    def __init__(self, id: str, name: str, arguments: str) -> None:
        self.id = id
        self.function = SimpleNamespace(name=name, arguments=arguments)


class FakeChoice:
    def __init__(self, message: SimpleNamespace) -> None:
        self.message = message


class FakeResponse:
    def __init__(self, text: str, tool_calls: list[FakeToolCall] | None = None) -> None:
        msg = SimpleNamespace(
            content=text,
            tool_calls=tool_calls or [],
            model="deepseek-v4-flash",
        )
        self.choices = [FakeChoice(msg)]
        self.usage = SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30)


class FakeUsage:
    def __init__(self) -> None:
        self.prompt_tokens = 10
        self.completion_tokens = 20
        self.total_tokens = 30


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
        current_content="Evaluá mi TP, encontré problemas en la resolución?",
        career="Ing. en Sistemas",
        user_preferences={},
    )


@pytest.fixture
def fake_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mockea list_documents y read_document con datos sintéticos."""

    def _list_documents(ctx: ToolContext, modulo_id: int | None = None) -> dict[str, Any]:
        return {
            "ok": True,
            "tool": "list_documents",
            "documents": [
                {"id": 10, "filename": "enunciado.pdf", "status": "ready", "size": 5000},
                {"id": 11, "filename": "resolucion.pdf", "status": "ready", "size": 8000},
            ],
            "count": 2,
        }

    def _read_document(
        ctx: ToolContext, document_id: int, max_chars: int | None = None
    ) -> dict[str, Any]:
        docs = {
            10: "Enunciado: implementar un shell básico con fork/exec.",
            11: "Resolución: usé system() en vez de fork/exec.",
        }
        text = docs.get(document_id, "")
        return {
            "ok": True,
            "tool": "read_document",
            "document_id": document_id,
            "filename": f"doc{document_id}.pdf",
            "text": text,
            "chunks_total": 1,
            "total_chars": len(text),
            "returned_chars": len(text),
            "truncated": False,
        }

    monkeypatch.setitem(REGISTRY, "list_documents", REGISTRY["list_documents"].__class__(
        name="list_documents",
        description=REGISTRY["list_documents"].description,
        fn=_list_documents,
        args_schema=REGISTRY["list_documents"].args_schema,
    ))
    monkeypatch.setitem(REGISTRY, "read_document", REGISTRY["read_document"].__class__(
        name="read_document",
        description=REGISTRY["read_document"].description,
        fn=_read_document,
        args_schema=REGISTRY["read_document"].args_schema,
    ))


# ── Tests ────────────────────────────────────────────────────────
def test_agent_loop_executes_tools_iteratively(
    monkeypatch: pytest.MonkeyPatch,
    fake_state: AgentState,
    fake_documents: None,
) -> None:
    """El LLM llama list_documents → read_document(x2) → respuesta final."""

    call_count = {"n": 0}

    def fake_complete(
        self: Any,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> Any:
        from app.agent.llm import CompletionResult, TokenUsage

        call_count["n"] += 1
        # Después de la 1ra llamada, devolvemos tool_call(list_documents)
        if call_count["n"] == 1:
            return CompletionResult(
                text="",
                model="deepseek-v4-flash",
                usage=TokenUsage(10, 20, 30),
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "list_documents",
                        "arguments": {},
                        "arguments_raw": "{}",
                    }
                ],
            )
        # 2da: tool_call(read_document, id=10)
        if call_count["n"] == 2:
            return CompletionResult(
                text="",
                model="deepseek-v4-flash",
                usage=TokenUsage(10, 20, 30),
                tool_calls=[
                    {
                        "id": "call_2",
                        "name": "read_document",
                        "arguments": {"document_id": 10},
                        "arguments_raw": json.dumps({"document_id": 10}),
                    }
                ],
            )
        # 3ra: tool_call(read_document, id=11)
        if call_count["n"] == 3:
            return CompletionResult(
                text="",
                model="deepseek-v4-flash",
                usage=TokenUsage(10, 20, 30),
                tool_calls=[
                    {
                        "id": "call_3",
                        "name": "read_document",
                        "arguments": {"document_id": 11},
                        "arguments_raw": json.dumps({"document_id": 11}),
                    }
                ],
            )
        # 4ta: respuesta final
        return CompletionResult(
            text=(
                "El enunciado pide fork/exec pero tu resolución usa system(); "
                "eso es exactamente el error que el TP quería evitar."
            ),
            model="deepseek-v4-flash",
            usage=TokenUsage(50, 60, 110),
            tool_calls=[],
        )

    monkeypatch.setattr(
        "app.agent.llm.GoClient.complete", fake_complete,
    )

    result = agent_loop_mod.agent_loop(fake_state)

    assert call_count["n"] == 4, f"esperaba 4 llamadas, obtuve {call_count['n']}"
    assert "fork/exec" in result["final_text"]
    assert "system()" in result["final_text"]
    assert result["tools_used"] == ["list_documents", "read_document"]
    assert result["iterations"] == 4
    tool_call_entries = [e for e in result["tool_calls_log"] if e.get("kind") == "tool_call"]
    assert len(tool_call_entries) == 3
    for entry in tool_call_entries:
        assert entry["ok"] is True
    # El log también incluye entradas ``llm_call`` / ``llm_response``
    # (una por iteración) — verificamos que estén en orden.
    llm_call_entries = [e for e in result["tool_calls_log"] if e.get("kind") == "llm_call"]
    llm_response_entries = [e for e in result["tool_calls_log"] if e.get("kind") == "llm_response"]
    assert len(llm_call_entries) == 4
    assert len(llm_response_entries) == 4


def test_agent_loop_handles_tool_error_gracefully(
    monkeypatch: pytest.MonkeyPatch,
    fake_state: AgentState,
) -> None:
    """Si una tool falla, el loop reporta el error y el LLM puede seguir."""

    def fake_complete(
        self: Any,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> Any:
        from app.agent.llm import CompletionResult, TokenUsage

        # 1ra: tool_call a una tool inexistente.
        if not any(m.get("role") == "tool" for m in messages):
            return CompletionResult(
                text="",
                model="deepseek-v4-flash",
                usage=TokenUsage(10, 20, 30),
                tool_calls=[
                    {
                        "id": "call_x",
                        "name": "tool_inexistente",
                        "arguments": {},
                        "arguments_raw": "{}",
                    }
                ],
            )
        # 2da: respuesta final (con el tool error en contexto).
        return CompletionResult(
            text="Hubo un error al buscar los documentos.",
            model="deepseek-v4-flash",
            usage=TokenUsage(10, 20, 30),
            tool_calls=[],
        )

    monkeypatch.setattr(
        "app.agent.llm.GoClient.complete", fake_complete,
    )

    result = agent_loop_mod.agent_loop(fake_state)

    assert "error" in result["final_text"].lower()
    assert result["tools_used"] == ["tool_inexistente"]
    tool_call_entries = [e for e in result["tool_calls_log"] if e.get("kind") == "tool_call"]
    assert tool_call_entries[0]["ok"] is False
    assert "tool desconocida" in tool_call_entries[0]["error"]


def test_agent_loop_respects_max_iterations(
    monkeypatch: pytest.MonkeyPatch,
    fake_state: AgentState,
) -> None:
    """Si el LLM no converge, el loop corta en MAX_AGENT_ITERATIONS."""

    call_count = {"n": 0}

    def fake_complete(
        self: Any,
        *,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> Any:
        from app.agent.llm import CompletionResult, TokenUsage
        from app.agent.prompts import MAX_AGENT_ITERATIONS

        call_count["n"] += 1
        if call_count["n"] > MAX_AGENT_ITERATIONS:
            pytest.fail("se llamó al LLM más veces que MAX_AGENT_ITERATIONS")
        # Siempre devolvemos un tool_call para forzar el loop.
        return CompletionResult(
            text="",
            model="deepseek-v4-flash",
            usage=TokenUsage(10, 20, 30),
            tool_calls=[
                {
                    "id": f"call_{call_count['n']}",
                    "name": "get_user_memory",
                    "arguments": {},
                    "arguments_raw": "{}",
                }
            ],
        )

    monkeypatch.setattr(
        "app.agent.llm.GoClient.complete", fake_complete,
    )

    result = agent_loop_mod.agent_loop(fake_state)

    from app.agent.prompts import MAX_AGENT_ITERATIONS
    assert call_count["n"] == MAX_AGENT_ITERATIONS
    assert result["iterations"] == MAX_AGENT_ITERATIONS
