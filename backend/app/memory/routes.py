"""Memory router (Fase 6).

Endpoints:
  - ``GET /me/memory``              perfil + últimos 10 eventos + próximos 10.
  - ``GET /me/events?from=&to=``    eventos próximos (rango, default 60 días).
  - ``POST /me/events``             alta manual de un evento (útil para la UI).

Todos requieren JWT y devuelven sólo los datos del usuario autenticado.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.models import Event, User, UserProfile
from app.db.session import get_db
from app.schemas.event import EventCreateIn, EventListOut, EventOut, MemoryOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/me", tags=["memory"])


def _event_to_out(e: Event) -> EventOut:
    return EventOut(
        id=e.id,
        user_id=e.user_id,
        materia_id=e.materia_id,
        materia_name=e.materia.name if e.materia else None,
        type=e.type,
        date=e.date,
        description=e.description,
        created_at=e.created_at,
    )


@router.get("/memory", response_model=MemoryOut)
def get_memory(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MemoryOut:
    """Perfil del usuario + últimos 10 eventos + próximos 10."""
    profile: UserProfile | None = db.query(UserProfile).filter(
        UserProfile.user_id == current_user.id
    ).first()
    if profile is None:
        profile = UserProfile(user_id=current_user.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    try:
        prefs = json.loads(profile.preferences_json or "{}")
    except json.JSONDecodeError:
        prefs = {}

    now = datetime.now(UTC)
    recent = (
        db.execute(
            select(Event)
            .where(Event.user_id == current_user.id)
            .order_by(Event.created_at.desc(), Event.id.desc())
            .limit(10)
        )
        .scalars()
        .all()
    )
    upcoming = (
        db.execute(
            select(Event)
            .where(Event.user_id == current_user.id, Event.date >= now)
            .order_by(Event.date.asc(), Event.id.asc())
            .limit(10)
        )
        .scalars()
        .all()
    )
    return MemoryOut(
        user_id=current_user.id,
        name=current_user.name,
        email=current_user.email,
        career=profile.career,
        current_year=profile.current_year,
        preferences=prefs,
        recent_events=[_event_to_out(e) for e in recent],
        upcoming_events=[_event_to_out(e) for e in upcoming],
    )


@router.get("/events", response_model=EventListOut)
def list_events(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EventListOut:
    """Eventos del usuario en un rango. Default: hoy → hoy + 60 días."""
    now = datetime.now(UTC)
    start = from_ or now
    end = to or (now + timedelta(days=60))
    rows = (
        db.execute(
            select(Event)
            .where(
                Event.user_id == current_user.id,
                Event.date >= start,
                Event.date <= end,
            )
            .order_by(Event.date.asc(), Event.id.asc())
        )
        .scalars()
        .all()
    )
    return EventListOut(items=[_event_to_out(e) for e in rows])


@router.post("/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
def create_event(
    payload: EventCreateIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EventOut:
    """Alta manual de un evento académico. Usado por la UI o por el agente."""
    try:
        type_value = EventCreateIn.validate_type(payload.type)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(err),
        ) from err

    if payload.materia_id is not None:
        from app.db.models import Materia

        if db.get(Materia, payload.materia_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Materia inexistente",
            )

    event = Event(
        user_id=current_user.id,
        materia_id=payload.materia_id,
        type=type_value,
        date=payload.date,
        description=payload.description.strip(),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    logger.info(
        "memory.create_event user_id=%s type=%s materia_id=%s date=%s",
        current_user.id,
        type_value,
        payload.materia_id,
        payload.date.isoformat(),
    )
    return _event_to_out(event)


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    event = db.get(Event, event_id)
    if event is None or event.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evento no encontrado",
        )
    db.delete(event)
    db.commit()
