"""Pydantic schemas for chats (Fase 2)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatCreate(BaseModel):
    modulo_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=255)


class ChatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    modulo_id: int
    title: str
    created_at: datetime


class ChatListOut(BaseModel):
    items: list[ChatOut]
