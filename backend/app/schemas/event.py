"""Pydantic schemas for events and memory (Fase 6)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import EVENT_TYPES


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    materia_id: int | None
    materia_name: str | None = None
    type: str
    date: datetime
    description: str
    created_at: datetime


class EventListOut(BaseModel):
    items: list[EventOut]


class EventCreateIn(BaseModel):
    """Schema para crear un event vía REST (Fase 6)."""

    materia_id: int | None = None
    type: str = Field(default="otro", max_length=32)
    date: datetime
    description: str = Field(min_length=1, max_length=512)

    @classmethod
    def validate_type(cls, value: str) -> str:
        v = (value or "").strip().lower()
        if v not in EVENT_TYPES:
            raise ValueError(
                f"type inválido: {value!r}. Permitidos: {', '.join(EVENT_TYPES)}"
            )
        return v


class MemoryOut(BaseModel):
    """Snapshot consolidado de la memoria del usuario."""

    user_id: int
    name: str
    email: str
    career: str
    current_year: int | None
    preferences: dict[str, Any] = {}
    recent_events: list[EventOut] = []
    upcoming_events: list[EventOut] = []
