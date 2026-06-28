"""Agent tools (function-calling loop).

Cada tool es una función pura (o con side-effect acotado a SQLite/Chroma)
que recibe un ``ToolContext`` y devuelve un dict. El ``agent_loop`` del
grafo las orquesta vía ``app.agent.tools.registry.REGISTRY``.

Tools expuestas:
  - ``list_documents``         lista los archivos subidos en la materia/módulo.
  - ``read_document``          lee el contenido completo de un documento.
  - ``rag_search``             wrapper de ``app.agent.rag.search``.
  - ``get_user_memory``        lee perfil + próximos eventos del estudiante.
  - ``update_user_memory``     actualiza preferences/year.
  - ``list_upcoming_events``   eventos del estudiante en un rango.
  - ``set_event``              crea un evento académico.

El resumen de un documento se genera únicamente durante la ingestión
(``app/documents/processing.py``) y queda cacheado en
``Document.summary``. No es una tool del agente.

Las tools abren su propia sesión de SQLAlchemy (mismo patrón que
``documents.processing``) y son robustas a fallos: si una tool falla, el
loop sigue con la siguiente y reporta el error como un resultado legible.
"""
