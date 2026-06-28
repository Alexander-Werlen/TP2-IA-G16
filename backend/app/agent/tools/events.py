"""Event tools (Fase 6).

``list_upcoming_events``  →  eventos del user en un rango de fechas.
``set_event``  →  crea un evento académico (parcial, entrega, final, etc.).

Guardrails de ``set_event``:
  - ``materia_id`` (si viene) debe existir en la tabla ``materias``.
  - ``type`` debe estar en la whitelist ``EVENT_TYPES``.
  - ``date`` debe ser parseable a ``datetime`` y no estar en el pasado lejano
    (aceptamos hasta 5 años en el pasado por tolerancia a typos).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.agent.tools.context import ToolContext, ToolResult, err, ok
from app.db.models import EVENT_TYPES, Event, Materia
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

NAME_LIST = "list_upcoming_events"
NAME_SET = "set_event"

# Ventana por defecto si no se pasa rango: hoy → hoy + 60 días.
DEFAULT_WINDOW_DAYS = 60
# Cuánto permitimos ir hacia el pasado (tolerancia a "ayer" mal escrito).
PAST_TOLERANCE_DAYS = 365 * 5


def _parse_date(value: Any) -> datetime | None:
    """Acepta ``datetime``, string ISO-8601, ``YYYY-MM-DD`` o ``DD/MM/YYYY``."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # Si trae timezone, la respetamos. Si no, asumimos UTC.
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def list_upcoming_events(
    ctx: ToolContext,
    *,
    from_: str | datetime | None = None,
    to: str | datetime | None = None,
) -> ToolResult:
    """Lista eventos del user en el rango [from, to]. Default: hoy → +60 días."""
    db = SessionLocal()
    try:
        now = datetime.now(UTC)
        start = _parse_date(from_) if from_ else now
        end = _parse_date(to) if to else (now + timedelta(days=DEFAULT_WINDOW_DAYS))
        if start is None or end is None:
            return err("from/to inválidos (usar ISO-8601 o YYYY-MM-DD)")
        rows = (
            db.execute(
                select(Event)
                .where(
                    Event.user_id == ctx.user_id,
                    Event.date >= start,
                    Event.date <= end,
                )
                .order_by(Event.date.asc(), Event.id.asc())
            )
            .scalars()
            .all()
        )
        return ok(
            events=[
                {
                    "id": e.id,
                    "type": e.type,
                    "date": e.date.isoformat(),
                    "description": e.description,
                    "materia_id": e.materia_id,
                }
                for e in rows
            ],
            count=len(rows),
            window={"from": start.isoformat(), "to": end.isoformat()},
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("list_upcoming_events tool falló")
        return err(f"list_upcoming_events: {exc.__class__.__name__}")
    finally:
        db.close()


def set_event(
    ctx: ToolContext,
    *,
    type: str,  # noqa: A002  (el nombre del arg tiene que ser 'type' para el LLM)
    date: str | datetime,
    description: str,
    materia_id: int | None = None,
) -> ToolResult:
    """Crea un evento académico. Devuelve el id del nuevo evento."""
    type_norm = (type or "").strip().lower()
    if type_norm not in EVENT_TYPES:
        return err(f"type inválido: {type!r}. Permitidos: {', '.join(EVENT_TYPES)}")
    dt = _parse_date(date)
    if dt is None:
        return err(f"date inválida: {date!r} (usar ISO-8601 o YYYY-MM-DD)")
    if dt < datetime.now(UTC) - timedelta(days=PAST_TOLERANCE_DAYS):
        return err("date demasiado en el pasado")
    desc = (description or "").strip()
    if not desc:
        return err("description vacía")
    if len(desc) > 512:
        desc = desc[:512]

    db = SessionLocal()
    try:
        if materia_id is not None and db.get(Materia, materia_id) is None:
            return err(f"materia_id {materia_id} no existe")
        event = Event(
            user_id=ctx.user_id,
            materia_id=materia_id,
            type=type_norm,
            date=dt,
            description=desc,
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        logger.info(
            "tool.set_event user_id=%s id=%s type=%s date=%s materia_id=%s",
            ctx.user_id, event.id, type_norm, dt.isoformat(), materia_id,
        )
        return ok(
            event_id=event.id,
            type=type_norm,
            date=dt.isoformat(),
            description=desc,
            materia_id=materia_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("set_event tool falló")
        db.rollback()
        return err(f"set_event: {exc.__class__.__name__}")
    finally:
        db.close()
