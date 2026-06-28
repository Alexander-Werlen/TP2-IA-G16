"""Modulos router (Fase 2).

Endpoints:
- ``GET  /modulos?materia_id=``  lista los módulos del usuario autenticado
  (opcionalmente filtrados por materia).
- ``POST /modulos``              crea un módulo del usuario en una materia.
- ``DELETE /modulos/{id}``       borra un módulo (y sus chats/messages en
  cascada). El usuario sólo puede borrar los propios.

Todos los endpoints requieren JWT.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.auth.deps import get_current_user
from app.db.models import Materia, Modulo, User
from app.db.session import get_db
from app.schemas.modulo import ModuloCreate, ModuloListOut, ModuloOut

router = APIRouter(prefix="/modulos", tags=["modulos"])


def _to_out(m: Modulo) -> ModuloOut:
    return ModuloOut(
        id=m.id,
        materia_id=m.materia_id,
        materia_name=m.materia.name,
        materia_code=m.materia.code,
        materia_year=m.materia.year,
        name=m.name,
        created_at=m.created_at,
    )


@router.get("", response_model=ModuloListOut)
def list_modulos(
    materia_id: int | None = Query(default=None, gt=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ModuloListOut:
    stmt = (
        select(Modulo)
        .options(joinedload(Modulo.materia))
        .where(Modulo.user_id == current_user.id)
        .order_by(Modulo.materia_id, Modulo.created_at, Modulo.id)
    )
    if materia_id is not None:
        stmt = stmt.where(Modulo.materia_id == materia_id)
    rows = db.execute(stmt).scalars().unique().all()
    return ModuloListOut(items=[_to_out(m) for m in rows])


@router.post("", response_model=ModuloOut, status_code=status.HTTP_201_CREATED)
def create_modulo(
    payload: ModuloCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ModuloOut:
    materia = db.get(Materia, payload.materia_id)
    if materia is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La materia indicada no existe",
        )

    name = payload.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El nombre del módulo no puede estar vacío",
        )

    modulo = Modulo(
        user_id=current_user.id,
        materia_id=materia.id,
        name=name,
    )
    db.add(modulo)
    db.commit()
    db.refresh(modulo)

    return _to_out(modulo)


@router.delete("/{modulo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_modulo(
    modulo_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    modulo = db.get(Modulo, modulo_id)
    if modulo is None or modulo.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Módulo no encontrado",
        )
    db.delete(modulo)
    db.commit()
