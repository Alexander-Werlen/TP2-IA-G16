"""Pydantic schemas for messages (Fase 2)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8192)
    model: str | None = Field(
        default=None,
        max_length=64,
        description="Modelo LLM solicitado. En Fase 2 es ignorado (eco).",
    )


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chat_id: int
    role: str
    content: str
    model_used: str | None
    created_at: datetime


class MessageListOut(BaseModel):
    items: list[MessageOut]


class MessageSendOut(BaseModel):
    user_message: MessageOut
    assistant_message: MessageOut
