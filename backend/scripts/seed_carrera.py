"""Script manual para correr el seed de la carrera (CLI).

Uso (dentro del contenedor):
    docker compose exec api python -m scripts.seed_carrera

O local:
    cd backend && python -m scripts.seed_carrera
"""
from __future__ import annotations

import sys

from app.carrera.seed import MATERIAS, seed_carrera


def main() -> int:
    print(f"Semillas a insertar (idempotente): {len(MATERIAS)} materias")
    inserted = seed_carrera()
    if inserted == 0:
        print("Nada nuevo: la tabla 'materias' ya estaba poblada.")
    else:
        print(f"Insertadas {inserted} materias nuevas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
