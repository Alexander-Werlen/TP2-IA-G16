"""TutorIA FastAPI application entrypoint.

Fase 1: lifespan que corre el seed de la carrera al startup.
Las migraciones de Alembic las aplica el entrypoint del contenedor antes
de levantar uvicorn (ver Dockerfile).
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agent.routes import router as agent_router
from app.auth.routes import router as auth_router
from app.carrera.routes import router as carrera_router
from app.carrera.seed import seed_carrera
from app.chats.routes import router as chats_router
from app.db import models  # noqa: F401  (registra modelos en Base.metadata)
from app.documents.routes import router as documents_router
from app.memory.routes import router as memory_router
from app.messages.routes import router as messages_router
from app.modulos.routes import router as modulos_router

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        inserted = seed_carrera()
        if inserted:
            logger.info("Seed de la carrera OK (%d filas nuevas).", inserted)
    except Exception:  # noqa: BLE001
        # No queremos que la API no arranque por un fallo de seed;
        # el endpoint /carrera simplemente devolverá 0 materias.
        logger.exception("Falló el seed de la carrera, continuando sin él.")
    yield


app = FastAPI(
    title="TutorIA API",
    version="0.1.0",
    description="Backend del agente académico TutorIA.",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    return {"service": "tutoria-api", "phase": 1}


@app.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(carrera_router)
app.include_router(modulos_router)
app.include_router(chats_router)
app.include_router(messages_router)
app.include_router(documents_router)
app.include_router(memory_router)
app.include_router(agent_router)
