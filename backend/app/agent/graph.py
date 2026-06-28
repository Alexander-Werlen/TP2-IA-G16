"""LangGraph agent (function-calling loop).

Arma el ``StateGraph`` con los nodos ``agent_loop → memory``. Con la
migración a function-calling, el nodo ``agent_loop`` reemplaza a los
antiguos ``perceive``, ``plan``, ``retrieve``, ``tools`` y ``answer``.

El grafo se compila una vez y se reusa por request. Para el caso de uso
(chat académico con memoria) la ejecución es síncrona — LangGraph 0.6
permite ``invoke()`` sobre un dict y devuelve el estado final. El
streaming hacia la UI se hace en el endpoint ``/agent/stream``
envolviendo la ejecución y emitiendo deltas del nodo ``agent_loop``
como eventos SSE.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.nodes.agent_loop import agent_loop
from app.agent.nodes.memory import memory
from app.agent.state import AgentState

logger = logging.getLogger(__name__)


def build_graph() -> Any:
    """Compila y devuelve el StateGraph. Se cachea por proceso."""
    g = StateGraph(AgentState)

    g.add_node("agent_loop", agent_loop)
    g.add_node("memory", memory)

    g.add_edge(START, "agent_loop")
    g.add_edge("agent_loop", "memory")
    g.add_edge("memory", END)

    return g.compile()


_graph = None


def get_graph() -> Any:
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def reset_graph() -> None:
    """Para tests: descarta el grafo cacheado."""
    global _graph
    _graph = None


def run(initial_state: AgentState) -> AgentState:
    """Ejecuta el grafo y devuelve el estado final."""
    return get_graph().invoke(initial_state)


def stream_events(initial_state: AgentState) -> Iterator[dict[str, Any]]:
    """Itera los eventos del grafo. Cada evento es un dict con
    ``node`` (el nodo que acaba de terminar) y ``state`` (su output).
    """
    for event in get_graph().stream(initial_state):
        # event = {node_name: {delta}}
        for node_name, delta in event.items():
            yield {"node": node_name, "state": delta}
