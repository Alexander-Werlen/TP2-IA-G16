"""Tests para ``_tool_result_to_message`` y el manejo de context length errors.

Cubrimos:
  - Tool results grandes (100k+ chars) pasan sin truncar al mensaje.
  - Errores de OpenAI por context length se detectan y producen mensajes
    legibles para el usuario (no crípticos ``[error del LLM: ...]``).
  - El loop no-stream devuelve el mensaje amable cuando OpenAI tira
    ``BadRequestError`` con ``code=context_length_exceeded``.
  - El loop stream emite un evento ``error`` con el mensaje amable y
    ``code=context_length_exceeded``.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from openai import BadRequestError

from app.agent.nodes import agent_loop as agent_loop_mod
from app.agent.nodes.agent_loop import (
    _CONTEXT_LENGTH_MSG,
    _is_context_length_error,
    _tool_result_to_message,
)
from app.agent.state import AgentState
from app.agent.tools.registry import REGISTRY


# ── Tests de _tool_result_to_message ────────────────────────────
class TestToolResultToMessage:
    def test_short_tool_result_passes_through(self) -> None:
        result = {
            "ok": True,
            "tool": "list_documents",
            "documents": [{"id": 1, "filename": "a.pdf"}],
            "count": 1,
        }
        msg = _tool_result_to_message("call_1", result)
        assert msg["role"] == "tool"
        assert msg["tool_call_id"] == "call_1"
        # No debe truncarse.
        assert "truncado" not in msg["content"]
        payload = json.loads(msg["content"])
        assert payload["documents"][0]["filename"] == "a.pdf"
        # El campo ``tool`` no se mete en el payload (es metadata).
        assert "tool" not in payload

    def test_large_tool_result_is_not_truncated(self) -> None:
        """Un tool result de 100k chars pasa completo al LLM."""
        big_text = "x" * 100_000
        result = {
            "ok": True,
            "tool": "read_document",
            "text": big_text,
            "truncated": False,
        }
        msg = _tool_result_to_message("call_1", result)
        # La longitud del content incluye la serialización JSON del dict.
        # Lo importante: NO debe tener el sufijo "...(truncado)".
        assert "truncado" not in msg["content"]
        payload = json.loads(msg["content"])
        assert len(payload["text"]) == 100_000

    def test_error_result_becomes_error_string(self) -> None:
        result = {
            "ok": False,
            "tool": "read_document",
            "error": "documento 5 no encontrado",
        }
        msg = _tool_result_to_message("call_1", result)
        assert msg["content"] == "ERROR: documento 5 no encontrado"

    def test_non_serializable_payload_falls_back_to_str(self) -> None:
        # Un set no es JSON-serializable, debe caer a str().
        result = {
            "ok": True,
            "tool": "x",
            "weird": {1, 2, 3},
        }
        msg = _tool_result_to_message("call_1", result)
        # No rompe.
        assert msg["role"] == "tool"
        assert msg["content"]


# ── Tests de _is_context_length_error ───────────────────────────
def _make_bad_request_error(
    *, code: str | None = None, body: dict | None = None, msg: str = ""
) -> BadRequestError:
    """Construye un BadRequestError con los atributos que el helper inspecciona."""
    response = httpx.Response(
        status_code=400,
        request=httpx.Request("POST", "https://api.example.com/v1/chat/completions"),
    )
    err = BadRequestError(
        message=msg or "irrelevant",
        response=response,
        body=body or {"error": {}},
    )
    if code is not None:
        # ``code`` se setea como atributo en runtime; forzamos.
        object.__setattr__(err, "code", code)
    return err


class TestIsContextLengthError:
    def test_detects_via_code_attribute(self) -> None:
        err = _make_bad_request_error(code="context_length_exceeded")
        assert _is_context_length_error(err) is True

    def test_detects_via_body_code(self) -> None:
        err = _make_bad_request_error(body={"error": {"code": "context_length_exceeded"}})
        assert _is_context_length_error(err) is True

    def test_detects_via_body_type(self) -> None:
        err = _make_bad_request_error(body={"error": {"type": "context_length_exceeded"}})
        assert _is_context_length_error(err) is True

    def test_detects_via_message_substring(self) -> None:
        err = _make_bad_request_error(
            msg="This model's maximum context length is 8192 tokens",
        )
        assert _is_context_length_error(err) is True

    def test_returns_false_for_unrelated_bad_request(self) -> None:
        err = _make_bad_request_error(
            code="invalid_api_key",
            body={"error": {"code": "invalid_api_key"}},
            msg="Incorrect API key",
        )
        assert _is_context_length_error(err) is False

    def test_returns_false_for_non_openai_exception(self) -> None:
        assert _is_context_length_error(ValueError("boom")) is False


# ── Tests del loop no-stream con context length error ───────────
def _fake_state() -> AgentState:
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
        current_content="leé el documento 1",
        career="Ing. en Sistemas",
        user_preferences={},
    )


def test_agent_loop_returns_friendly_message_on_context_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si OpenAI tira context_length_exceeded, el loop devuelve el mensaje
    amable en vez de ``[error del LLM: ...]``.
    """
    from app.agent.llm import GoClient

    def fake_complete(
        self: GoClient,
        *,
        messages: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> Any:
        # Tiramos el BadRequestError como haría la API real.
        raise _make_bad_request_error(
            code="context_length_exceeded",
            body={"error": {"code": "context_length_exceeded"}},
            msg="context_length_exceeded: too many tokens",
        )

    monkeypatch.setattr("app.agent.llm.GoClient.complete", fake_complete)

    result = agent_loop_mod.agent_loop(_fake_state())

    assert _CONTEXT_LENGTH_MSG in result["final_text"]
    assert "max_chars" in result["final_text"]
    assert result["iterations"] == 1


def test_agent_loop_stream_emits_friendly_error_on_context_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """En el stream, el context length error sale como evento ``error``."""
    from app.agent.llm import GoClient

    def fake_stream(
        self: GoClient,
        *,
        messages: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> Any:
        raise _make_bad_request_error(
            code="context_length_exceeded",
            body={"error": {"code": "context_length_exceeded"}},
            msg="context_length_exceeded: too many tokens",
        )

    # La función de módulo importa GoClient y llama a self.stream().
    # Monkeypatcheamos el método ``stream`` directamente.
    monkeypatch.setattr("app.agent.llm.GoClient.stream", fake_stream)

    events = list(agent_loop_mod.agent_loop_stream(_fake_state()))

    error_events = [e for e in events if e.get("event") == "error"]
    assert len(error_events) == 1
    err_event = error_events[0]
    assert err_event["code"] == "context_length_exceeded"
    assert _CONTEXT_LENGTH_MSG in err_event["message"]


def test_agent_loop_other_errors_still_return_cryptic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Errores que no son context length siguen devolviendo el mensaje genérico."""
    from app.agent.llm import GoClient

    def fake_complete(
        self: GoClient,
        *,
        messages: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> Any:
        raise _make_bad_request_error(
            code="invalid_api_key",
            msg="Incorrect API key provided",
        )

    monkeypatch.setattr("app.agent.llm.GoClient.complete", fake_complete)

    result = agent_loop_mod.agent_loop(_fake_state())

    assert "BadRequestError" in result["final_text"]
    assert "context_length" not in result["final_text"]


# ── Test integración: tool result grande pasa por el loop ───────
def test_large_tool_result_passes_through_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test end-to-end: el LLM recibe el tool result completo, sin truncar."""
    big_text = "x" * 50_000
    tool_result = {
        "ok": True,
        "tool": "read_document",
        "document_id": 1,
        "filename": "x.pdf",
        "text": big_text,
        "truncated": False,
        "chunks_total": 10,
        "total_chars": 50_000,
        "returned_chars": 50_000,
    }

    # Inyectamos el tool result en el REGISTRY (mockeamos read_document).
    monkeypatch.setitem(REGISTRY, "read_document", REGISTRY["read_document"].__class__(
        name="read_document",
        description=REGISTRY["read_document"].description,
        fn=lambda ctx, document_id, max_chars=None: tool_result,
        args_schema=REGISTRY["read_document"].args_schema,
    ))

    captured_messages: list[list[dict[str, Any]]] = []
    call_count = {"n": 0}

    def fake_complete(
        self: Any,
        *,
        messages: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> Any:
        from app.agent.llm import CompletionResult, TokenUsage

        call_count["n"] += 1
        captured_messages.append(list(messages))
        if call_count["n"] == 1:
            # 1ra: tool_call a read_document.
            return CompletionResult(
                text="",
                model="deepseek-v4-flash",
                usage=TokenUsage(10, 20, 30),
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "read_document",
                        "arguments": {"document_id": 1},
                        "arguments_raw": json.dumps({"document_id": 1}),
                    }
                ],
            )
        # 2da: respuesta final.
        return CompletionResult(
            text="listo",
            model="deepseek-v4-flash",
            usage=TokenUsage(10, 20, 30),
            tool_calls=[],
        )

    monkeypatch.setattr("app.agent.llm.GoClient.complete", fake_complete)

    result = agent_loop_mod.agent_loop(_fake_state())

    assert call_count["n"] == 2
    # En la 2da llamada, el historial incluye el tool result. Buscamos el
    # mensaje role:tool y verificamos que el texto NO esté truncado.
    second_call = captured_messages[1]
    tool_messages = [m for m in second_call if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    tool_msg = tool_messages[0]
    assert "truncado" not in tool_msg["content"]
    payload = json.loads(tool_msg["content"])
    assert len(payload["text"]) == 50_000
    assert result["final_text"] == "listo"
