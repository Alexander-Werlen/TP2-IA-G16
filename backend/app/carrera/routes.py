"""Carrera router (Fase 1).

`GET /carrera` devuelve el árbol anidado por año. Es público (no requiere
auth) porque sólo expone la estructura institucional de la carrera.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.carrera.seed import CAREER_NAME, YEAR_LABELS
from app.db.models import Materia
from app.db.session import get_db

router = APIRouter(prefix="/carrera", tags=["carrera"])


class MateriaNode(BaseModel):
    id: int
    code: str
    name: str


class YearNode(BaseModel):
    year: int
    name: str
    materias: list[MateriaNode]


class CarreraOut(BaseModel):
    career: str
    years: list[YearNode]


@router.get("", response_model=CarreraOut)
def get_carrera(db: Session = Depends(get_db)) -> CarreraOut:
    rows = db.execute(select(Materia).order_by(Materia.year, Materia.id)).scalars().all()

    by_year: dict[int, list[MateriaNode]] = {}
    for m in rows:
        by_year.setdefault(m.year, []).append(MateriaNode(id=m.id, code=m.code, name=m.name))

    years = [
        YearNode(year=y, name=YEAR_LABELS.get(y, f"{y}.º año"), materias=by_year.get(y, []))
        for y in sorted(by_year.keys())
    ]
    return CarreraOut(career=CAREER_NAME, years=years)
