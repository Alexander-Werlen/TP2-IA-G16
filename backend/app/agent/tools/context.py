"""Tool context y tipos comunes (Fase 6).

Cada tool recibe un ``ToolContext`` con todo lo que necesita para operar
(id del usuario, id de la materia, sesión de DB) y devuelve un dict con
un campo ``ok`` (bool) y un ``result`` o ``error``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolContext:
    """Snapshot inmutable del contexto del agente al invocar una tool."""

    user_id: int
    materia_id: int | None
    materia_name: str
    modulo_name: str
    chat_id: int


ToolResult = dict[str, Any]


def ok(**fields: Any) -> ToolResult:
    """Helper para construir un ToolResult exitoso."""
    return {"ok": True, **fields}


def err(message: str, **fields: Any) -> ToolResult:
    """Helper para construir un ToolResult fallido."""
    return {"ok": False, "error": message, **fields}
