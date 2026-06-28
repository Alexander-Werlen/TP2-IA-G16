from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from openai import APIError as OpenAIAPIError
from openai import AsyncOpenAI, OpenAI
from openai.types.chat import ChatCompletionMessageToolCall

from app.config import Settings

logger = logging.getLogger(__name__)


class ModelNotAllowedError(ValueError):
    """El modelo pedido no está en la whitelist de ``Settings.allowed_models``."""


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None


@dataclass(frozen=True)
class CompletionResult:
    text: str
    model: str
    usage: TokenUsage
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class GoClient:
    """Cliente LLM vía OpenCode GO (OpenAI-compatible)."""

    def __init__(self, settings: Settings) -> None:
        if not settings.opencode_go_api_key:
            raise RuntimeError(
                "OPENCODE_GO_API_KEY no está configurada. Definila en .env antes de "
                "levantar el backend."
            )
        self._settings = settings
        self._client = OpenAI(
            api_key=settings.opencode_go_api_key,
            base_url=settings.opencode_go_base_url,
        )
        self._async_client: AsyncOpenAI | None = None

    @property
    def allowed_models(self) -> list[str]:
        return list(self._settings.allowed_models_list)

    @property
    def default_model(self) -> str:
        return self._settings.default_model

    @property
    def openai_client(self) -> OpenAI:
        """Expone el cliente de OpenAI para callers que necesitan control
        total del shape de mensajes (ej: agent_loop con tool messages)."""
        return self._client

    @property
    def async_openai_client(self) -> AsyncOpenAI:
        """Cliente OpenAI async, lazy-instanciado.

        Lo usa ``astream()`` para que el agent_loop_async pueda esperar
        los chunks del LLM sin bloquear el event loop. Si nunca se
        llama, no se instancia.
        """
        if self._async_client is None:
            self._async_client = AsyncOpenAI(
                api_key=self._settings.opencode_go_api_key,
                base_url=self._settings.opencode_go_base_url,
            )
        return self._async_client

    def validate_model(self, model: str) -> None:
        if model not in self.allowed_models:
            raise ModelNotAllowedError(
                f"Modelo {model!r} no permitido. Permitidos: {self.allowed_models}"
            )

    @staticmethod
    def _thinking_mode(model: str) -> dict | None:
        if model.startswith("deepseek-"):
            return {"thinking_mode": "high"}
        return None

    @staticmethod
    def _build_messages(
        history: Sequence[dict[str, str]],
        current_content: str,
        system_instruction: str,
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_instruction}
        ]
        for msg in history:
            role = "assistant" if msg["role"] == "assistant" else "user"
            messages.append({"role": role, "content": msg["content"]})
        messages.append({"role": "user", "content": current_content})
        return messages

    def complete(
        self,
        *,
        history: Sequence[dict[str, str]],
        current_content: str,
        system_instruction: str,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> CompletionResult:
        used_model = model or self.default_model
        self.validate_model(used_model)

        extra = self._thinking_mode(used_model)
        if messages is None:
            messages = self._build_messages(history, current_content, system_instruction)
        kwargs: dict[str, Any] = {
            "model": used_model,
            "messages": messages,
            "stream": False,
            "extra_body": extra,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"
        try:
            response = self._client.chat.completions.create(**kwargs)
        except OpenAIAPIError:
            logger.exception("GoClient.complete() falló (model=%s).", used_model)
            raise

        choice = response.choices[0] if response.choices else None
        text = (choice.message.content or "").strip() if choice else ""
        tool_calls = _serialize_tool_calls(choice.message.tool_calls) if choice else []
        usage_raw = response.usage
        usage = TokenUsage(
            prompt_tokens=getattr(usage_raw, "prompt_tokens", None),
            completion_tokens=getattr(usage_raw, "completion_tokens", None),
            total_tokens=getattr(usage_raw, "total_tokens", None),
        )
        return CompletionResult(text=text, model=used_model, usage=usage, tool_calls=tool_calls)

    def stream(
        self,
        *,
        history: Sequence[dict[str, str]],
        current_content: str,
        system_instruction: str,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> Iterator[tuple[str, str, list[dict[str, Any]]]]:
        """Stream de un solo LLM call.

        Yields tuplas ``(delta_text, model, tool_calls_so_far)``. El primer
        yielded siempre es ``("", used_model, [])``. Cuando el LLM emite
        ``tool_calls`` (caso function-calling), los deltas de texto quedan
        vacíos y ``tool_calls_so_far`` trae la lista completa al final del
        stream.
        """
        used_model = model or self.default_model
        self.validate_model(used_model)

        yield ("", used_model, [])

        extra = self._thinking_mode(used_model)
        if messages is None:
            messages = self._build_messages(history, current_content, system_instruction)
        kwargs: dict[str, Any] = {
            "model": used_model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": False},
            "extra_body": extra,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"

        try:
            stream = self._client.chat.completions.create(**kwargs)
            accumulated_calls: list[ChatCompletionMessageToolCall] = []
            finish_reason: str | None = None
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    yield (delta.content, used_model, [])
                if delta.tool_calls:
                    accumulated_calls = _merge_tool_call_deltas(accumulated_calls, delta.tool_calls)
                if chunk.choices[0].finish_reason:
                    finish_reason = chunk.choices[0].finish_reason
            if finish_reason == "tool_calls" and accumulated_calls:
                yield ("", used_model, _serialize_tool_calls(accumulated_calls))
        except OpenAIAPIError:
            logger.exception("GoClient.stream() falló (model=%s).", used_model)
            raise

    async def astream(
        self,
        *,
        history: Sequence[dict[str, str]],
        current_content: str,
        system_instruction: str,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[tuple[str, str, list[dict[str, Any]]]]:
        """Versión async de :meth:`stream`. Usa ``AsyncOpenAI`` y ``await``.

        El comportamiento es idéntico: yields tuplas ``(delta_text,
        used_model, tool_calls_so_far)``. La diferencia es que cada chunk
        se await-ea, así que **no bloquea el event loop** mientras espera
        el próximo token. Esto es clave para que el SSE flushee al
        cliente apenas llega cada delta.
        """
        used_model = model or self.default_model
        self.validate_model(used_model)

        yield ("", used_model, [])

        extra = self._thinking_mode(used_model)
        if messages is None:
            messages = self._build_messages(history, current_content, system_instruction)
        kwargs: dict[str, Any] = {
            "model": used_model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": False},
            "extra_body": extra,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"

        try:
            stream = await self.async_openai_client.chat.completions.create(**kwargs)
            accumulated_calls: list[ChatCompletionMessageToolCall] = []
            finish_reason: str | None = None
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    yield (delta.content, used_model, [])
                if delta.tool_calls:
                    accumulated_calls = _merge_tool_call_deltas(
                        accumulated_calls, delta.tool_calls
                    )
                if chunk.choices[0].finish_reason:
                    finish_reason = chunk.choices[0].finish_reason
            if finish_reason == "tool_calls" and accumulated_calls:
                yield ("", used_model, _serialize_tool_calls(accumulated_calls))
        except OpenAIAPIError:
            logger.exception("GoClient.astream() falló (model=%s).", used_model)
            raise


def _merge_tool_call_deltas(
    accumulated: list[ChatCompletionMessageToolCall],
    deltas: list,
) -> list[ChatCompletionMessageToolCall]:
    """Acumula los deltas de tool_calls que llegan en chunks separados.

    La API de streaming emite un primer chunk con ``id`` y ``name``, y
    varios chunks siguientes con sólo ``arguments`` parciales. Vamos
    rebuildeando in-place por índice.
    """
    out = list(accumulated)
    for delta in deltas:
        idx = getattr(delta, "index", None) or 0
        while len(out) <= idx:
            out.append(None)  # type: ignore[arg-type]
        existing = out[idx]
        if existing is None:
            out[idx] = ChatCompletionMessageToolCall(
                id=getattr(delta, "id", "") or "",
                type="function",
                function={
                    "name": getattr(getattr(delta, "function", None), "name", "") or "",
                    "arguments": getattr(getattr(delta, "function", None), "arguments", "") or "",
                },
            )
        else:
            new_args = (
                getattr(getattr(delta, "function", None), "arguments", "") or ""
            )
            merged_args = (existing.function.arguments or "") + new_args
            merged_name = (
                getattr(getattr(delta, "function", None), "name", None)
                or existing.function.name
            )
            existing_id = existing.id or getattr(delta, "id", "") or ""
            out[idx] = ChatCompletionMessageToolCall(
                id=existing_id,
                type="function",
                function={"name": merged_name, "arguments": merged_args},
            )
    return [c for c in out if c is not None]


def _serialize_tool_calls(
    calls: list[ChatCompletionMessageToolCall] | None,
) -> list[dict[str, Any]]:
    """Convierte tool_calls del SDK a un dict JSON-serializable."""
    if not calls:
        return []
    out: list[dict[str, Any]] = []
    for c in calls:
        args_raw = getattr(c.function, "arguments", "") or ""
        try:
            args_parsed = json.loads(args_raw) if args_raw else {}
        except json.JSONDecodeError:
            args_parsed = {"_raw": args_raw}
        out.append(
            {
                "id": c.id,
                "name": c.function.name,
                "arguments": args_parsed,
                "arguments_raw": args_raw,
            }
        )
    return out
