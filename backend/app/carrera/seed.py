"""Seed de la carrera Ing. en Sistemas (Fase 1).

Lista hardcodeada a partir de `docs/materias.txt`. El seed es idempotente:
se usa INSERT OR IGNORE por `code`, así que se puede correr muchas veces
sin duplicar filas.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.models import Materia
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

CAREER_NAME = "Ing. en Sistemas"

# (year, code, name). Los `code` son slug-like, únicos, legibles.
MATERIAS: list[tuple[int, str, str]] = [
    (1, "AM1", "Análisis Matemático I"),
    (1, "AGA", "Álgebra y Geometría Analítica"),
    (1, "LED", "Lógica y Estructuras Discretas"),
    (1, "SPN", "Sistemas y Procesos de Negocio"),
    (1, "AED", "Algoritmos y Estructura de Datos"),
    (1, "AC", "Arquitectura de Computadoras"),
    (1, "FIS1", "Física I"),
    (1, "ING1", "Inglés I"),
    (2, "MS", "Matemática Superior"),
    (2, "AM2", "Análisis Matemático II"),
    (2, "FIS2", "Física II"),
    (2, "ASI", "Análisis de Sistemas de Información"),
    (2, "SSL", "Sintaxis y Semántica de los Lenguajes"),
    (2, "PP", "Paradigmas de Programación"),
    (2, "SO", "Sistemas Operativos"),
    (2, "OE", "Organización Empresarial"),
    (3, "PE", "Probabilidad y Estadísticas"),
    (3, "DSI", "Diseño de Sistemas de Información"),
    (3, "BD", "Bases de Datos"),
    (3, "DS", "Desarrollo de Software"),
    (3, "CD", "Comunicación de Datos"),
    (3, "IS", "Ingeniería y Sociedad"),
    (3, "ECO", "Economía"),
    (3, "ING2", "Inglés II"),
    (3, "AN", "Análisis Numérico"),
    (4, "ICS", "Ingeniería y Calidad de Software"),
    (4, "RD", "Redes de Datos"),
    (4, "IO", "Investigación Operativa"),
    (4, "SIM", "Simulación"),
    (4, "TA", "Tecnologías para la Automatización"),
    (4, "ASI-ADM", "Administración de Sistemas de Información"),
    (4, "LEG", "Legislación"),
    (5, "IA", "Inteligencia Artificial"),
    (5, "CD-DATOS", "Ciencia de Datos"),
    (5, "SG", "Sistemas de Gestión"),
    (5, "GG", "Gestión Gerencial"),
    (5, "SSI", "Seguridad en los Sistemas de Información"),
    (5, "PF", "Proyecto Final"),
]

YEAR_LABELS: dict[int, str] = {
    1: "1.º año",
    2: "2.º año",
    3: "3.º año",
    4: "4.º año",
    5: "5.º año",
}


def _bulk_insert(db: Session, rows: Iterable[tuple[int, str, str]]) -> int:
    rows = list(rows)
    if not rows:
        return 0

    stmt = sqlite_insert(Materia).values([{"code": c, "name": n, "year": y} for y, c, n in rows])
    # No sobreescribimos si la fila ya existe.
    stmt = stmt.on_conflict_do_nothing(index_elements=[Materia.code])
    result = db.execute(stmt)
    db.commit()
    # rowcount en INSERT...ON CONFLICT DO NOTHING = filas efectivamente insertadas.
    return int(result.rowcount or 0)


def seed_carrera(db: Session | None = None) -> int:
    """Inserta la carrera. Devuelve la cantidad de filas efectivamente creadas."""
    owns_session = db is None
    session = db or SessionLocal()
    try:
        # Verificación rápida: si ya está todo, no hacemos nada.
        existing = session.scalar(select(Materia.id).limit(1))
        if existing is not None:
            logger.info("seed_carrera: la tabla 'materias' ya tiene filas, skip.")
            return 0
        inserted = _bulk_insert(session, MATERIAS)
        logger.info("seed_carrera: %d materias insertadas.", inserted)
        return inserted
    finally:
        if owns_session:
            session.close()
