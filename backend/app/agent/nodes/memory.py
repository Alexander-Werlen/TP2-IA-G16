"""Nodo ``memory``: punto de extensión.

En la arquitectura con function-calling, los side-effects de memoria
(``update_user_memory``, ``set_event``) ya se aplican dentro del nodo
``agent_loop`` cuando el LLM decide invocar esas tools. Este nodo queda
como no-op para preservar el shape del grafo y como hook futuro
(persistencia de ``final_text``, etc.).
"""
from __future__ import annotations

import logging

from app.agent.state import AgentState

logger = logging.getLogger(__name__)


def memory(state: AgentState) -> AgentState:
    used = state.get("tools_used") or []
    logger.info("memory node reached; tools_used=%s", used)
    return {}
