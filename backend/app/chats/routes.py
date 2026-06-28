"""Chats router (Fase 2 + Fase 3).

Endpoints:
- ``GET  /chats?modulo_id=``                lista los chats del usuario.
- ``POST /chats``                           crea un chat en un módulo del usuario.
- ``DELETE /chats/{id}``                    borra un chat y sus mensajes.
- ``GET  /chats/{id}/messages``             historial de mensajes.
- ``POST /chats/{id}/messages``             envía un mensaje y devuelve la
  respuesta completa del LLM (no-streaming, JSON).
- ``POST /chats/{id}/messages/stream``      idem pero con streaming SSE
  (definido en ``app/agent/routes.py``).

Todos los endpoints requieren JWT y validan ownership del recurso.
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from openai import APIError as OpenAIAPIError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.llm import GoClient, ModelNotAllowedError
from app.agent.prompts import HISTORY_WINDOW, build_system_instruction
from app.auth.deps import get_current_user
from app.config import get_settings
from app.db.models import Chat, Materia, Message, Modulo, User
from app.db.session import get_db
from app.schemas.chat import ChatCreate, ChatListOut, ChatOut
from app.schemas.message import MessageCreate, MessageListOut, MessageOut, MessageSendOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chats", tags=["chats"])


def _get_owned_modulo(db: Session, modulo_id: int, user: User) -> Modulo:
    modulo = db.get(Modulo, modulo_id)
    if modulo is None or modulo.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Módulo no encontrado",
        )
    return modulo


def _get_owned_chat(db: Session, chat_id: int, user: User) -> Chat:
    chat = db.get(Chat, chat_id)
    if chat is None or chat.modulo.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat no encontrado",
        )
    return chat


def _chat_to_out(chat: Chat) -> ChatOut:
    return ChatOut(
        id=chat.id,
        modulo_id=chat.modulo_id,
        title=chat.title,
        created_at=chat.created_at,
    )


def _message_to_out(m: Message) -> MessageOut:
    return MessageOut(
        id=m.id,
        chat_id=m.chat_id,
        role=m.role,
        content=m.content,
        model_used=m.model_used,
        created_at=m.created_at,
    )


@router.get("", response_model=ChatListOut)
def list_chats(
    modulo_id: int | None = Query(default=None, gt=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatListOut:
    stmt = (
        select(Chat)
        .join(Modulo, Chat.modulo_id == Modulo.id)
        .where(Modulo.user_id == current_user.id)
        .order_by(Chat.modulo_id, Chat.created_at, Chat.id)
    )
    if modulo_id is not None:
        stmt = stmt.where(Chat.modulo_id == modulo_id)
    rows = db.execute(stmt).scalars().unique().all()
    return ChatListOut(items=[_chat_to_out(c) for c in rows])


@router.post("", response_model=ChatOut, status_code=status.HTTP_201_CREATED)
def create_chat(
    payload: ChatCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatOut:
    _get_owned_modulo(db, payload.modulo_id, current_user)

    title = payload.title.strip()
    if not title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El título del chat no puede estar vacío",
        )

    chat = Chat(modulo_id=payload.modulo_id, title=title)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return _chat_to_out(chat)


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat(
    chat_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    chat = _get_owned_chat(db, chat_id, current_user)
    db.delete(chat)
    db.commit()


@router.get("/{chat_id}/messages", response_model=MessageListOut)
def list_messages(
    chat_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageListOut:
    _get_owned_chat(db, chat_id, current_user)
    rows = (
        db.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at, Message.id)
        )
        .scalars()
        .all()
    )
    return MessageListOut(items=[_message_to_out(m) for m in rows])


@router.post(
    "/{chat_id}/messages",
    response_model=MessageSendOut,
    status_code=status.HTTP_201_CREATED,
)
def send_message(
    chat_id: int,
    payload: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageSendOut:
    """Guarda el mensaje del usuario y devuelve la respuesta del LLM.

    En Fase 3 el ``assistant`` se genera con el LLM configurado (default
    ``deepseek-v4-flash``; el cliente puede sobreescribirlo con ``model``).
    El endpoint **no** streama: la variante con streaming SSE vive en
    ``POST /chats/{id}/messages/stream`` (``app/agent/routes.py``).
    """
    chat = _get_owned_chat(db, chat_id, current_user)

    content = payload.content.strip()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El mensaje no puede estar vacío",
        )

    settings = get_settings()
    requested_model = payload.model or settings.default_model
    client = GoClient(settings)
    try:
        client.validate_model(requested_model)
    except ModelNotAllowedError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(err),
        ) from err

    user_msg = Message(
        chat_id=chat_id,
        role="user",
        content=content,
        model_used=None,
    )
    db.add(user_msg)
    db.flush()

    # Resolver materia/módulo para el system_instruction.
    modulo: Modulo = chat.modulo
    materia: Materia | None = db.get(Materia, modulo.materia_id)
    if materia is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Materia asociada al módulo no existe",
        )

    # Historial previo (sin contar el user_msg recién insertado).
    history_rows = (
        db.execute(
            select(Message)
            .where(Message.chat_id == chat_id, Message.id != user_msg.id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(HISTORY_WINDOW)
        )
        .scalars()
        .all()
    )
    history = [
        {"role": r.role, "content": r.content} for r in reversed(history_rows)
    ]

    system_instruction = build_system_instruction(
        career="Ing. en Sistemas",
        year=materia.year,
        materia=materia.name,
        modulo=modulo.name,
    )

    start = time.perf_counter()
    try:
        result = client.complete(
            history=history,
            current_content=content,
            system_instruction=system_instruction,
            model=requested_model,
        )
    except OpenAIAPIError as err:
        logger.exception(
            "chats.send_message: GoClient APIError chat_id=%s user_id=%s model=%s",
            chat_id,
            current_user.id,
            requested_model,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error del LLM: {err.__class__.__name__}: {err}",
        ) from err

    latency_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "chats.send_message OK chat_id=%s user_id=%s model=%s "
        "tokens_in=%s tokens_out=%s latency_ms=%s chars=%d",
        chat_id,
        current_user.id,
        result.model,
        result.usage.prompt_tokens,
        result.usage.completion_tokens,
        latency_ms,
        len(result.text),
    )

    assistant_msg = Message(
        chat_id=chat_id,
        role="assistant",
        content=result.text,
        model_used=result.model,
    )
    db.add(assistant_msg)
    db.commit()
    db.refresh(user_msg)
    db.refresh(assistant_msg)

    return MessageSendOut(
        user_message=_message_to_out(user_msg),
        assistant_message=_message_to_out(assistant_msg),
    )
