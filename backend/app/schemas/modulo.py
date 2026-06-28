"""Pydantic schemas for modules (Fase 2)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ModuloCreate(BaseModel):
    materia_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=255)


class ModuloOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    materia_id: int
    materia_name: str
    materia_code: str
    materia_year: int
    name: str
    created_at: datetime


class ModuloListOut(BaseModel):
    items: list[ModuloOut]
