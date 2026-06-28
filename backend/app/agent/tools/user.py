"""User memory tools (Fase 6).

``get_user_memory``  →  lee perfil del UserProfile + lista próximos 5 eventos.
``update_user_memory``  →  actualiza preferences (merge JSON) y/o current_year.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.tools.context import ToolContext, ToolResult, err, ok
from app.db.models import Event, UserProfile
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

NAME_GET = "get_user_memory"
NAME_UPDATE = "update_user_memory"


def _read_profile(db: Session, user_id: int) -> tuple[UserProfile | None, dict]:
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if profile is None:
        return None, {}
    try:
        prefs = json.loads(profile.preferences_json or "{}")
    except json.JSONDecodeError:
        prefs = {}
    return profile, prefs


def get_user_memory(ctx: ToolContext) -> ToolResult:
    """Lee perfil + últimos 5 eventos próximos."""
    db = SessionLocal()
    try:
        profile, prefs = _read_profile(db, ctx.user_id)
        if profile is None:
            return err("perfil no encontrado")
        now = datetime.now(UTC)
        upcoming = (
            db.execute(
                select(Event)
                .where(Event.user_id == ctx.user_id, Event.date >= now)
                .order_by(Event.date.asc(), Event.id.asc())
                .limit(5)
            )
            .scalars()
            .all()
        )
        return ok(
            user_id=ctx.user_id,
            career=profile.career,
            current_year=profile.current_year,
            preferences=prefs,
            upcoming_events=[
                {
                    "id": e.id,
                    "type": e.type,
                    "date": e.date.isoformat(),
                    "description": e.description,
                    "materia_id": e.materia_id,
                }
                for e in upcoming
            ],
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("get_user_memory tool falló")
        return err(f"get_user_memory: {exc.__class__.__name__}")
    finally:
        db.close()


def update_user_memory(
    ctx: ToolContext,
    *,
    preferences: dict | None = None,
    current_year: int | None = None,
) -> ToolResult:
    """Actualiza preferencias (merge) y/o año actual del usuario.

    Validación mínima: ``current_year`` debe estar entre 1 y 5 (la carrera
    tiene 5 años). Si se pasa algo fuera de rango, se rechaza.
    """
    if current_year is not None and not (1 <= current_year <= 6):
        return err("current_year fuera de rango (1-6)")
    if preferences is not None and not isinstance(preferences, dict):
        return err("preferences debe ser un dict")
    db = SessionLocal()
    try:
        profile, prefs = _read_profile(db, ctx.user_id)
        if profile is None:
            profile = UserProfile(user_id=ctx.user_id)
            db.add(profile)
            db.flush()
        if preferences:
            prefs.update(preferences)
            profile.preferences_json = json.dumps(prefs, ensure_ascii=False, sort_keys=True)
        if current_year is not None:
            profile.current_year = current_year
        db.commit()
        logger.info(
            "tool.update_user_memory user_id=%s prefs_keys=%s year=%s",
            ctx.user_id,
            list(preferences.keys()) if preferences else [],
            current_year,
        )
        return ok(
            career=profile.career,
            current_year=profile.current_year,
            preferences=prefs,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("update_user_memory tool falló")
        db.rollback()
        return err(f"update_user_memory: {exc.__class__.__name__}")
    finally:
        db.close()
