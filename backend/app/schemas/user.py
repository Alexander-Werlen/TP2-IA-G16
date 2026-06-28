"""User-related Pydantic schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    created_at: datetime


class UserProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    career: str
    current_year: int | None = None
    preferences: dict[str, Any] = {}


class MeResponse(BaseModel):
    user: UserOut
    profile: UserProfileOut
