"""Smoke tests del grafo con function-calling.

Verifica que el ``StateGraph`` se compila y que el nodo ``agent_loop``
está bien cableado (sin LLM real — todo mockeado).
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agent.graph import build_graph, get_graph, reset_graph
from app.agent.state import AgentState


def test_graph_compiles() -> None:
    """El StateGraph debe compilar sin errores."""
    reset_graph()
    g = build_graph()
    assert g is not None
    # get_graph() debe devolver el singleton cacheado
    g2 = get_graph()
    assert type(g2) is type(g)


def test_graph_runs_with_mocked_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """El grafo corre end-to-end con el LLM mockeado."""
    from app.agent.llm import CompletionResult, TokenUsage

    call_count = {"n": 0}

    def fake_complete(
        self: Any,
        *,
        messages: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> Any:
        call_count["n"] += 1
        return CompletionResult(
            text="hola, soy el tutor",
            model="deepseek-v4-flash",
            usage=TokenUsage(10, 20, 30),
            tool_calls=[],
        )

    monkeypatch.setattr("app.agent.llm.GoClient.complete", fake_complete)

    state: AgentState = {
        "user_id": 1,
        "chat_id": 1,
        "materia_id": 1,
        "materia_name": "Sistemas Operativos",
        "materia_year": 3,
        "modulo_id": 1,
        "modulo_name": "TP1",
        "model": "deepseek-v4-flash",
        "history": [],
        "current_content": "hola",
        "career": "Ing. en Sistemas",
        "user_preferences": {},
    }

    result = get_graph().invoke(state)

    assert result["final_text"] == "hola, soy el tutor"
    assert result["tools_used"] == []
    assert result["iterations"] == 1
    assert call_count["n"] == 1


def test_openai_schema_for_all_tools() -> None:
    """Todas las tools tienen un schema OpenAI bien formado."""
    from app.agent.tools.registry import openai_tools

    tools = openai_tools()
    assert len(tools) == 7  # list_documents, read_document, rag_search, get_user_memory, update_user_memory, list_upcoming_events, set_event
    for spec in tools:
        assert spec["type"] == "function"
        fn = spec["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn
        params = fn["parameters"]
        assert params.get("type") == "object"
        assert "properties" in params


def test_registry_includes_new_tools() -> None:
    """Las tools nuevas (list_documents, read_document) están registradas y
    las legacy (summarize_document) fueron removidas del agente.
    """
    from app.agent.tools.registry import REGISTRY

    assert "list_documents" in REGISTRY
    assert "read_document" in REGISTRY
    assert "rag_search" in REGISTRY
    assert "get_user_memory" in REGISTRY
    assert "set_event" in REGISTRY
    assert "list_upcoming_events" in REGISTRY
    assert "update_user_memory" in REGISTRY
    # summarize_document fue removida del agente: el resumen se genera
    # únicamente en la ingestión (ver app/documents/processing.py).
    assert "summarize_document" not in REGISTRY
