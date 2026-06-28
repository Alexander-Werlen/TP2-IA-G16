"""Agent router (function-calling loop).

Endpoints:
  - ``POST /chats/{chat_id}/messages/stream``  body ``{content, model?}`` →
    streaming SSE con el pipeline completo del agente LangGraph.
    Eventos: ``meta`` → ``phase``* → ``llm_call`` → (``token``* /
    ``tool_call``*) → ``llm_response`` → (``tool_result``* → ...)* →
    ``done``/``error``. (También puede emitir un ``tools`` consolidado
    al final para compatibilidad con el frontend viejo.)
  - ``POST /agent/stream``  alias del anterior, con ``{chat_id, content,
    model}`` en el body (útil para tests sin necesidad de un chat
    persistido).

El streaming de los tokens del LLM se hace dentro del nodo
``agent_loop_astream`` con function-calling nativo usando
``AsyncOpenAI`` para no bloquear el event loop. El LLM decide qué
tools llamar (si es que llama alguna) y el backend las ejecuta; cada
tool_call / tool_result se emite como evento SSE para que la UI pueda
mostrar progreso en tiempo real. ``llm_call`` y ``llm_response``
marcan el inicio y fin de cada llamada al LLM (con metadatos de la
iteración) y son la base del DebugPanel de la UI.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from openai import APIError as OpenAIAPIError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.llm import GoClient, ModelNotAllowedError
from app.agent.nodes.agent_loop import agent_loop_astream
from app.agent.prompts import HISTORY_WINDOW
from app.agent.state import AgentState
from app.agent.streaming import sse_format, sse_format_json, sse_response
from app.auth.deps import get_current_user
from app.config import get_settings
from app.db.models import Chat, Materia, Message, Modulo, User, UserProfile
from app.db.session import SessionLocal
from app.schemas.message import MessageCreate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent"])


# ── helpers ────────────────────────────────────────────────────────
def _client() -> GoClient:
    return GoClient(get_settings())


def _resolve_chat_chain(db: Session, chat_id: int, user: User) -> tuple[Chat, Modulo, Materia]:
    chat = db.get(Chat, chat_id)
    if chat is None or chat.modulo.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat no encontrado",
        )
    modulo = chat.modulo
    materia = db.get(Materia, modulo.materia_id)
    if materia is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Materia asociada al módulo no existe",
        )
    return chat, modulo, materia


def _load_user_prefs(db: Session, user_id: int) -> dict:
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if profile is None:
        return {}
    try:
        return json.loads(profile.preferences_json or "{}")
    except json.JSONDecodeError:
        return {}


def _build_initial_state(
    *,
    user_id: int,
    chat_id: int,
    materia_id: int,
    materia_name: str,
    materia_year: int,
    modulo_id: int | None,
    modulo_name: str,
    model: str,
    history: list[dict[str, str]],
    current_content: str,
    user_prefs: dict,
) -> AgentState:
    return AgentState(
        user_id=user_id,
        chat_id=chat_id,
        materia_id=materia_id,
        materia_name=materia_name,
        materia_year=materia_year,
        modulo_id=modulo_id,
        modulo_name=modulo_name,
        model=model,
        history=history,
        current_content=current_content,
        career="Ing. en Sistemas",
        user_preferences=user_prefs,
    )


# ── /agent/stream (Fase 6 + function-calling) ─────────────────────
class AgentStreamBody(BaseModel):
    chat_id: int = Field(gt=0)
    content: str = Field(min_length=1, max_length=8192)
    model: str | None = Field(default=None, max_length=64)


@router.post("/agent/stream", responses={200: {"content": {("text/event-stream"): {}}}})
async def stream_agent(body: AgentStreamBody, current_user: User = Depends(get_current_user)) -> StreamingResponse:
    """Endpoint del agente con function-calling nativo.

    El body lleva el ``chat_id`` (no estamos atados a la URL). El mensaje
    del usuario se persiste antes de empezar el stream.
    """
    content = body.content.strip()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El mensaje no puede estar vacío",
        )
    settings = get_settings()
    requested_model = body.model or settings.default_model
    try:
        _client().validate_model(requested_model)
    except ModelNotAllowedError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(err),
        ) from err

    # Validación de ownership + carga de contexto + persistencia del user msg.
    # También creamos el placeholder assistant acá (NO dentro del generator)
    # para minimizar la latencia pre-stream: el primer yield del SSE es
    # ``meta`` con los IDs ya conocidos.
    db = SessionLocal()
    try:
        chat, modulo, materia = _resolve_chat_chain(db, body.chat_id, current_user)
        materia_id = materia.id
        materia_name = materia.name
        materia_year = materia.year
        modulo_id = modulo.id
        modulo_name = modulo.name
        user_prefs = _load_user_prefs(db, current_user.id)

        user_msg = Message(
            chat_id=body.chat_id,
            role="user",
            content=content,
            model_used=None,
        )
        db.add(user_msg)
        db.flush()
        user_message_id = user_msg.id

        # Placeholder assistant (se actualizará al final del stream).
        assistant_msg = Message(
            chat_id=body.chat_id,
            role="assistant",
            content="",
            model_used=requested_model,
        )
        db.add(assistant_msg)
        db.commit()
        db.refresh(user_msg)
        db.refresh(assistant_msg)
        assistant_message_id = assistant_msg.id

        history_rows = (
            db.execute(
                select(Message)
                .where(Message.chat_id == body.chat_id, Message.id != user_message_id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(HISTORY_WINDOW)
            )
            .scalars()
            .all()
        )
        history = [
            {"role": r.role, "content": r.content} for r in reversed(history_rows)
        ]
    finally:
        db.close()

    async def event_gen() -> AsyncIterator[bytes]:
        used_model = requested_model
        unique: list[str] = []
        accumulated: list[str] = []
        start = time.perf_counter()
        # Sesión dedicada para las updates de final/error. La abrimos
        # lazy para no agregar latencia al primer yield.
        gen: Session | None = None
        try:
            # 1) ``meta`` sale apenas el cliente se conecta, así la UI ya
            # tiene los IDs de los mensajes para reconciliar después.
            yield sse_format_json(
                "meta",
                {
                    "user_message_id": user_message_id,
                    "assistant_message_id": assistant_message_id,
                    "model": used_model,
                },
            )

            # 2) agent_loop con function-calling (async stream).
            initial_state = _build_initial_state(
                user_id=current_user.id,
                chat_id=body.chat_id,
                materia_id=materia_id,
                materia_name=materia_name,
                materia_year=materia_year,
                modulo_id=modulo_id,
                modulo_name=modulo_name,
                model=used_model,
                history=history,
                current_content=content,
                user_prefs=user_prefs,
            )

            try:
                async for event in agent_loop_astream(initial_state):
                    kind = event.get("event")
                    if kind == "token":
                        accumulated.append(event["text"])
                        yield sse_format("token", event["text"])
                    elif kind == "tool_call":
                        yield sse_format_json("tool_call", {
                            "id": event["id"],
                            "name": event["name"],
                            "arguments": event["arguments"],
                            "description": event.get("description", event["name"]),
                            "display_args": event.get("display_args", {}),
                        })
                    elif kind == "tool_result":
                        name = event["tool"]
                        if name not in unique:
                            unique.append(name)
                        yield sse_format_json("tool_result", {
                            "tool": name,
                            "ok": event["ok"],
                            "summary": event["summary"],
                            "duration_ms": event.get("duration_ms", 0),
                            "description": event.get("description", name),
                        })
                    elif kind == "phase":
                        yield sse_format_json("phase", {"phase": event["phase"]})
                    elif kind == "llm_call":
                        yield sse_format_json("llm_call", {
                            "iteration": event["iteration"],
                            "model": event["model"],
                            "messages_count": event["messages_count"],
                            "total_chars": event["total_chars"],
                        })
                    elif kind == "llm_response":
                        yield sse_format_json("llm_response", {
                            "iteration": event["iteration"],
                            "model": event["model"],
                            "finish_reason": event["finish_reason"],
                            "text_chars": event["text_chars"],
                            "tool_calls_count": event["tool_calls_count"],
                            "duration_ms": event["duration_ms"],
                        })
                    elif kind == "final":
                        used_model = event.get("model") or used_model
                    elif kind == "error":
                        # Persistimos el error en el assistant message
                        # para que quede registro.
                        try:
                            gen = SessionLocal()
                            err_msg_text = event.get("message", "agent_error")
                            content_so_far = "".join(accumulated) or f"[error] {err_msg_text}"
                            assistant_msg_db = gen.get(Message, assistant_message_id)
                            if assistant_msg_db is not None:
                                assistant_msg_db.content = content_so_far
                                assistant_msg_db.model_used = used_model
                                gen.commit()
                        except Exception:
                            logger.exception("agent.stream: error al persistir error")
                        finally:
                            if gen is not None:
                                gen.close()
                                gen = None
                        yield sse_format("error", json.dumps(
                            {"message": event.get("message", "agent_error"),
                             "code": event.get("code")},
                            ensure_ascii=False,
                        ))
                        return
            except OpenAIAPIError as err:
                logger.exception("agent.stream: GoClient APIError")
                err_msg = _short_api_error(err)
                content_so_far = "".join(accumulated) or f"[error] {err_msg}"
                try:
                    gen = SessionLocal()
                    assistant_msg_db = gen.get(Message, assistant_message_id)
                    if assistant_msg_db is not None:
                        assistant_msg_db.content = content_so_far
                        assistant_msg_db.model_used = used_model
                        gen.commit()
                except Exception:
                    logger.exception("agent.stream: error al persistir APIError")
                finally:
                    if gen is not None:
                        gen.close()
                        gen = None
                yield sse_format(
                    "error",
                    json.dumps(
                        {"message": err_msg, "code": err.code if hasattr(err, "code") else None},
                        ensure_ascii=False,
                    ),
                )
                return

            # 3) emitir evento ``tools`` consolidado (back-compat con el
            # frontend viejo que escucha este evento para badges).
            if unique:
                yield sse_format_json("tools", {"tools": unique})

            # 4) persistir y emitir done.
            full_text = "".join(accumulated)
            try:
                gen = SessionLocal()
                assistant_msg_db = gen.get(Message, assistant_message_id)
                if assistant_msg_db is not None:
                    assistant_msg_db.content = full_text
                    assistant_msg_db.model_used = used_model
                    gen.commit()
            except Exception:
                logger.exception("agent.stream: error al persistir assistant final")
            finally:
                if gen is not None:
                    gen.close()
                    gen = None

            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "agent.stream OK chat_id=%s user_id=%s model=%s tools=%s "
                "latency_ms=%s chars=%d",
                body.chat_id, current_user.id, used_model, unique, latency_ms, len(full_text),
            )
            yield sse_format_json(
                "done",
                {
                    "model": used_model,
                    "latency_ms": latency_ms,
                    "assistant_message_id": assistant_message_id,
                    "tools": unique,
                },
            )
        except Exception:  # noqa: BLE001
            logger.exception("agent.stream: error inesperado")
            yield sse_format(
                "error",
                json.dumps({"message": "internal_error"}, ensure_ascii=False),
            )
        finally:
            if gen is not None:
                gen.close()

    return sse_response(event_gen())


# ── /chats/{chat_id}/messages/stream (Fase 3) ──────────────────────
@router.post(
    "/chats/{chat_id}/messages/stream",
    responses={200: {"content": {("text/event-stream"): {}}}},
)
async def stream_chat_message(
    chat_id: int,
    payload: MessageCreate,
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Reusa el endpoint del agente apuntando al chat del path."""
    return await stream_agent(
        AgentStreamBody(chat_id=chat_id, content=payload.content, model=payload.model),
        current_user,
    )


def _short_api_error(err: OpenAIAPIError) -> str:
    raw = str(err).strip()
    if not raw:
        return err.__class__.__name__
    first_line = raw.splitlines()[0]
    return first_line[:300]
