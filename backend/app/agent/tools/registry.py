"""Tool registry (function-calling loop).

Expone un mapeo ``nombre → callable(ctx, **kwargs)`` que el
``agent_loop`` consume. La metadata adicional (``description``,
``args_schema``) se usa para:

  1. Documentación y validación.
  2. Inyectar la lista de tools al LLM en formato OpenAI
     (``ToolSpec.to_openai_schema()``).
"""
from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.agent.tools import documents, events, rag, user
from app.agent.tools.context import ToolContext, ToolResult

ToolFn = Callable[..., ToolResult]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    fn: ToolFn
    args_schema: dict[str, Any] = field(default_factory=dict)

    def to_openai_schema(self) -> dict[str, Any]:
        """Convierte el ``ToolSpec`` al formato OpenAI ``tools=[...]``."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": _normalize_schema(self.args_schema),
            },
        }


def _normalize_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Asegura que el schema tenga ``type=object`` y ``properties``."""
    if not schema:
        return {"type": "object", "properties": {}}
    out = dict(schema)
    out.setdefault("type", "object")
    out.setdefault("properties", {})
    return out


def _rag(ctx: ToolContext, query: str, k: int = 6) -> ToolResult:
    return rag.run(query, ctx, k=k)


def _get_user_memory(ctx: ToolContext) -> ToolResult:
    return user.get_user_memory(ctx)


def _update_user_memory(
    ctx: ToolContext,
    preferences: dict | None = None,
    current_year: int | None = None,
) -> ToolResult:
    return user.update_user_memory(ctx, preferences=preferences, current_year=current_year)


def _list_upcoming_events(
    ctx: ToolContext,
    from_: str | None = None,
    to: str | None = None,
) -> ToolResult:
    return events.list_upcoming_events(ctx, from_=from_, to=to)


def _set_event(
    ctx: ToolContext,
    type: str,  # noqa: A002
    date: str,
    description: str,
    materia_id: int | None = None,
) -> ToolResult:
    return events.set_event(
        ctx, type=type, date=date, description=description, materia_id=materia_id
    )


def _list_documents(ctx: ToolContext, modulo_id: int | None = None) -> ToolResult:
    return documents.list_documents(ctx, modulo_id=modulo_id)


def _read_document(
    ctx: ToolContext,
    document_id: int,
    max_chars: int | None = None,
) -> ToolResult:
    return documents.read_document(ctx, document_id=document_id, max_chars=max_chars)


REGISTRY: dict[str, ToolSpec] = {
    "list_documents": ToolSpec(
        name="list_documents",
        description=(
            "Lista los documentos subidos por el estudiante en la materia "
            "del chat (o en un módulo específico si se pasa modulo_id). "
            "Devuelve id, filename, status, size. Usar cuando el estudiante "
            "pregunte qué archivos subió, o cuando haya que decidir qué "
            "documentos leer antes de responder."
        ),
        fn=_list_documents,
        args_schema={
            "type": "object",
            "properties": {
                "modulo_id": {
                    "type": "integer",
                    "description": "ID del módulo específico (opcional). Si no se pasa, lista todos los documentos del estudiante en la materia del chat.",
                },
            },
        },
    ),
    "read_document": ToolSpec(
        name="read_document",
        description=(
            "Lee el contenido completo de un documento del estudiante por "
            "id. Devuelve el texto concatenado de todos los chunks, "
            "truncado a max_chars (default 200 000, ~50k tokens, "
            "suficiente para la mayoría de documentos académicos como "
            "proyectos finales o papers). Si el documento se truncó, la "
            "respuesta incluye first_section_seen, last_section_seen, "
            "sections_in_returned y sections_omitted para que decidas si "
            "necesitás ajustar max_chars o leerlo en otro orden. Usar "
            "cuando el estudiante pida revisar, evaluar, comparar o "
            "analizar un documento entero (por ejemplo: subir el "
            "enunciado y la resolución de un TP y pedir que encuentre "
            "problemas)."
        ),
        fn=_read_document,
        args_schema={
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "integer",
                    "description": "ID del documento a leer (obtenido previamente con list_documents o mencionado por el estudiante).",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Máximo de caracteres a devolver (default 200000, hard-cap 200000).",
                },
            },
            "required": ["document_id"],
        },
    ),
    "rag_search": ToolSpec(
        name="rag_search",
        description=(
            "Búsqueda semántica (RAG) en los apuntes del estudiante de la "
            "materia del chat. Devuelve los top-k chunks más relevantes. "
            "Usar cuando la pregunta requiera encontrar definiciones, "
            "explicaciones o secciones específicas dentro del material "
            "subido. Si necesitás el documento entero, usá read_document."
        ),
        fn=_rag,
        args_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "La consulta del estudiante (o reformulada para búsqueda semántica).",
                },
                "k": {
                    "type": "integer",
                    "description": "Cantidad de chunks (default 6, máx recomendado 20).",
                },
            },
            "required": ["query"],
        },
    ),
    "get_user_memory": ToolSpec(
        name="get_user_memory",
        description=(
            "Lee el perfil del estudiante (carrera, año, preferencias) y "
            "sus próximos 5 eventos académicos. Usar cuando la consulta "
            "pueda depender del contexto del estudiante (año actual, "
            "preferencias, agenda)."
        ),
        fn=_get_user_memory,
        args_schema={"type": "object", "properties": {}},
    ),
    "update_user_memory": ToolSpec(
        name="update_user_memory",
        description=(
            "Actualiza el perfil persistente del estudiante. Acepta "
            "preferencias (dict arbitrario) o current_year (int 1-6). Usar "
            "SOLO cuando el estudiante exprese explícitamente un cambio "
            "persistente."
        ),
        fn=_update_user_memory,
        args_schema={
            "type": "object",
            "properties": {
                "preferences": {
                    "type": "object",
                    "description": "Dict a mergear en preferences_json del estudiante.",
                },
                "current_year": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 6,
                    "description": "Año actual de la carrera (1-6).",
                },
            },
        },
    ),
    "list_upcoming_events": ToolSpec(
        name="list_upcoming_events",
        description=(
            "Lista eventos académicos del estudiante en un rango de "
            "fechas. Tipos: parcial, recuperatorio, final, entrega, "
            "exposicion, otro. Usar cuando pregunten por fechas, "
            "entregas, próximos parciales, agenda."
        ),
        fn=_list_upcoming_events,
        args_schema={
            "type": "object",
            "properties": {
                "from_": {
                    "type": "string",
                    "description": "Fecha inicio ISO-8601 (opcional).",
                },
                "to": {
                    "type": "string",
                    "description": "Fecha fin ISO-8601 (opcional).",
                },
            },
        },
    ),
    "set_event": ToolSpec(
        name="set_event",
        description=(
            "Registra un evento académico (parcial, entrega, final, etc.). "
            "Usar SOLO cuando el estudiante informe explícitamente una "
            "fecha relevante. Devuelve el id del evento creado."
        ),
        fn=_set_event,
        args_schema={
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": [
                        "parcial",
                        "recuperatorio",
                        "final",
                        "entrega",
                        "exposicion",
                        "otro",
                    ],
                },
                "date": {
                    "type": "string",
                    "description": "Fecha ISO-8601 (YYYY-MM-DD o con hora).",
                },
                "description": {
                    "type": "string",
                    "description": "Descripción legible del evento.",
                },
                "materia_id": {
                    "type": "integer",
                    "description": "ID de la materia asociada (opcional).",
                },
            },
            "required": ["type", "date", "description"],
        },
    ),
}


def all_specs() -> list[ToolSpec]:
    return list(REGISTRY.values())


def all_names() -> list[str]:
    return list(REGISTRY.keys())


def get(name: str) -> ToolSpec | None:
    return REGISTRY.get(name)


def openai_tools() -> list[dict[str, Any]]:
    """Devuelve la lista de tools en formato OpenAI para el LLM."""
    return [spec.to_openai_schema() for spec in all_specs()]


# Helpers de introspección (usados por tests / debug).
def _reload_all() -> None:
    """Para tests: reimporta los módulos de tools por si se monkey-patchearon."""
    for mod in (documents, events, rag, user):
        importlib.reload(mod)
