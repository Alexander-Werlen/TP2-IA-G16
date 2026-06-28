"""Tests para ``describe_tool_call``: descripciones humanas de tool_calls.

Sirve para que el frontend muestre mensajes en lenguaje natural
(``"Leyendo 'enunciado.pdf'…"``) en lugar del nombre crudo de la tool.

Estas descripciones son parte del contrato entre backend y frontend, así
que se testean con snapshots.
"""
from __future__ import annotations

import pytest

from app.agent.nodes.agent_loop import describe_tool_call, safe_display_args


# ── describe_tool_call ─────────────────────────────────────────
@pytest.mark.parametrize(
    "name, args, expected",
    [
        # list_documents
        ("list_documents", {}, "Listando documentos del módulo"),
        ("list_documents", {"modulo_id": 5}, "Listando documentos del módulo #5"),
        # read_document
        ("read_document", {"document_id": 10}, "Leyendo documento #10"),
        # rag_search
        ("rag_search", {"query": "qué es un thread"}, 'Buscando: "qué es un thread"'),
        ("rag_search", {"query": "deadlock", "k": 3}, 'Buscando: "deadlock" (3 chunks)'),
        # get_user_memory
        ("get_user_memory", {}, "Consultando tus preferencias"),
        # update_user_memory
        (
            "update_user_memory",
            {"preferences": {"brevity": True}},
            "Guardando preferencias",
        ),
        (
            "update_user_memory",
            {"current_year": 3},
            "Actualizando año actual a 3.º",
        ),
        # list_upcoming_events
        ("list_upcoming_events", {}, "Consultando tu agenda"),
        # set_event
        (
            "set_event",
            {
                "type": "parcial",
                "date": "2024-11-15",
                "description": "parcial de so",
            },
            "Agendando parcial del 2024-11-15",
        ),
        (
            "set_event",
            {"type": "entrega", "date": "2025-03-01", "description": "tp"},
            "Agendando entrega del 2025-03-01",
        ),
        # summarize_document
        ("summarize_document", {"document_id": 7}, "Resumiendo documento #7"),
    ],
)
def test_describe_tool_call_basic(name: str, args: dict, expected: str) -> None:
    assert describe_tool_call(name, args) == expected


def test_describe_tool_call_with_result_filename() -> None:
    """Si el result_summary trae un filename, lo agregamos a la descripción."""
    desc = describe_tool_call(
        "read_document",
        {"document_id": 10},
        result_summary={"filename": "enunciado.pdf", "total_chars": 5000},
    )
    assert "enunciado.pdf" in desc
    assert "5,000" in desc or "5000" in desc  # formato con separador de miles o sin


def test_describe_tool_call_with_list_count() -> None:
    """list_documents: si el result trae count, lo mostramos."""
    desc = describe_tool_call(
        "list_documents",
        {},
        result_summary={"count": 3, "documents": [{}, {}, {}]},
    )
    assert "3" in desc


def test_describe_tool_call_unknown_tool() -> None:
    """Tool desconocida → devuelve el nombre como fallback."""
    assert describe_tool_call("tool_inexistente", {"foo": 1}) == "tool_inexistente"


def test_describe_tool_call_empty_args_safe() -> None:
    """Ninguna tool debería romperse con args vacíos."""
    for name in (
        "list_documents",
        "read_document",
        "rag_search",
        "get_user_memory",
        "update_user_memory",
        "list_upcoming_events",
        "set_event",
        "summarize_document",
    ):
        out = describe_tool_call(name, {})
        assert isinstance(out, str) and out


# ── safe_display_args ──────────────────────────────────────────
def test_safe_display_args_rag() -> None:
    args = safe_display_args("rag_search", {"query": "foo", "k": 4})
    assert args == {"query": "foo", "k": 4}


def test_safe_display_args_read_document() -> None:
    args = safe_display_args("read_document", {"document_id": 10, "max_chars": 999})
    assert args == {"document_id": 10}


def test_safe_display_args_set_event_truncates_long_description() -> None:
    long = "x" * 200
    args = safe_display_args(
        "set_event",
        {"type": "otro", "date": "2025-01-01", "description": long},
    )
    assert "description" in args
    assert len(args["description"]) <= 80 + 1  # +1 por elipsis
    assert args["description"].endswith("…") or len(long) <= 80


def test_safe_display_args_filters_unknown_keys() -> None:
    """Cualquier key fuera de la whitelist se descarta."""
    args = safe_display_args(
        "rag_search", {"query": "foo", "secret": "should_be_dropped"}
    )
    assert "secret" not in args
    assert args == {"query": "foo"}


def test_safe_display_args_unknown_tool_returns_empty() -> None:
    assert safe_display_args("tool_inexistente", {"x": 1}) == {}
