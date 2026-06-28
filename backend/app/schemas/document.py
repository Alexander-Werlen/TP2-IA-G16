"""Pydantic schemas for documents (Fase 4)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import DOCUMENT_STATUSES


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    modulo_id: int
    materia_id: int
    filename: str
    mime: str
    size: int
    summary: str | None
    summary_model: str | None
    status: str
    error_message: str | None
    created_at: datetime


class DocumentListOut(BaseModel):
    items: list[DocumentOut]


class DocumentStatusOut(BaseModel):
    """Snapshot liviano para polling del estado de procesamiento."""

    id: int
    status: str
    summary: str | None
    error_message: str | None


def is_valid_status(value: str) -> bool:
    return value in DOCUMENT_STATUSES
