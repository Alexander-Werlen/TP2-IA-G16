"""Agent state (function-calling loop).

El estado que circula por el ``StateGraph`` se define en ``AgentState``.
Con la migración a function-calling nativo, los nodos ``perceive`` y
``plan`` se eliminan: el LLM decide qué tools llamar iterativamente
dentro del nodo ``agent_loop``. Por eso ``AgentState`` ya no lleva
``intent`` ni ``plan`` — solo el input del usuario y el output del loop.
"""
from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    """Estado que circula por el grafo.

    Los campos son opcionales (``total=False``) porque LangGraph sólo
    requiere que cada nodo devuelva los que modifica.
    """

    # Entrada (la consume agent_loop)
    user_id: int
    chat_id: int
    materia_id: int | None
    materia_name: str
    materia_year: int
    modulo_id: int | None
    modulo_name: str
    model: str
    history: list[dict[str, str]]  # [{"role": "user"|"assistant", "content": "..."}]
    current_content: str
    career: str
    user_preferences: dict[str, Any]  # snapshot al inicio (para system prompt)

    # Salida del nodo agent_loop
    final_text: str
    tools_used: list[str]  # nombres únicos invocados (para badges y trazabilidad)
    iterations: int  # cantidad de vueltas del agent loop
    tool_calls_log: list[dict[str, Any]]  # [{"tool", "args", "ok", "error"?}, ...]
