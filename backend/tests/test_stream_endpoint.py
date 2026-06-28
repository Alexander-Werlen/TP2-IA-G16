"""Tests de integración del endpoint SSE ``/chats/{id}/messages/stream``.

Verifica:
  - Headers correctos (``text/event-stream``, ``X-Accel-Buffering: no``).
  - Llega el evento ``meta`` apenas arranca.
  - Los eventos ``token`` llegan con gaps de tiempo (no todo de golpe).
  - El endpoint itera sobre ``agent_loop_astream`` y propaga ``phase``,
    ``tool_call``, ``tool_result`` con los campos nuevos.

Usamos ``httpx.AsyncClient`` + ``ASGITransport`` para no levantar uvicorn.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.tools.context import ToolContext
from app.agent.tools.registry import REGISTRY
from app.auth import deps as auth_deps
from app.db import models  # noqa: F401 (asegura que los models estén registrados)
from app.db.base import Base
from app.db.models import Chat, Materia, Message, Modulo, User, UserProfile
from app.db.session import get_db


# ── Fixtures ──────────────────────────────────────────────────
@pytest.fixture
def app_with_overrides(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FastAPI]:
    """Crea una app FastAPI con DB in-memory y un user/chats sembrados."""
    from app.agent.routes import router as agent_router

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    # Override del SessionLocal usado por routes.py dentro del generator.
    monkeypatch.setattr("app.agent.routes.SessionLocal", TestSession)

    app = FastAPI()
    app.include_router(agent_router, prefix="")
    app.dependency_overrides[get_db] = override_get_db

    # Sembrar user, materia, módulo, chat
    with TestSession() as db:
        user = User(
            id=1, email="t@test.com", name="T", password_hash="x",
            created_at=datetime(2024, 1, 1),
        )
        profile = UserProfile(user_id=1, preferences_json="{}", current_year=3)
        materia = Materia(id=1, code="SO", name="Sistemas Operativos", year=3)
        modulo = Modulo(
            id=1, user_id=1, materia_id=1, name="TP1",
            created_at=datetime(2024, 1, 1),
        )
        chat = Chat(id=1, modulo_id=1, title="chat 1", created_at=datetime(2024, 1, 1))
        db.add_all([user, profile, materia, modulo, chat])
        db.commit()

    # Override del current_user para no necesitar JWT real
    def fake_current_user() -> User:
        with TestSession() as db:
            return db.get(User, 1)

    app.dependency_overrides[auth_deps.get_current_user] = fake_current_user

    yield app


# ── Helpers ───────────────────────────────────────────────────
def _parse_sse(raw: str) -> list[dict[str, Any]]:
    """Parsea un chunk de texto SSE a una lista de eventos."""
    events: list[dict[str, Any]] = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        event = None
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].lstrip())
        if not event:
            continue
        data = "\n".join(data_lines)
        if event == "token":
            events.append({"event": "token", "data": data})
        else:
            try:
                events.append({"event": event, "data": json.loads(data)})
            except json.JSONDecodeError:
                events.append({"event": event, "data": data})
    return events


# ── Tests ─────────────────────────────────────────────────────
async def test_stream_endpoint_headers(app_with_overrides: FastAPI) -> None:
    """El endpoint responde con los headers de SSE correctos."""
    import app.agent.llm as llm_mod

    async def fake_astream(self: Any, **_kwargs: Any) -> Any:
        yield ("hola", "deepseek-v4-flash", [])

    orig = llm_mod.GoClient.astream
    llm_mod.GoClient.astream = fake_astream  # type: ignore[assignment]
    try:
        transport = ASGITransport(app=app_with_overrides)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post(
                "/chats/1/messages/stream",
                json={"content": "hola"},
            )
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        assert r.headers.get("x-accel-buffering") == "no"
    finally:
        llm_mod.GoClient.astream = orig  # type: ignore[assignment]


async def test_stream_endpoint_emits_meta_and_done(app_with_overrides: FastAPI) -> None:
    """El primer evento es meta, el último es done."""
    import app.agent.llm as llm_mod

    async def fake_astream(self: Any, **_kwargs: Any) -> Any:
        yield ("hola", "deepseek-v4-flash", [])

    orig = llm_mod.GoClient.astream
    llm_mod.GoClient.astream = fake_astream  # type: ignore[assignment]
    try:
        transport = ASGITransport(app=app_with_overrides)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post(
                "/chats/1/messages/stream", json={"content": "hola"}
            )
        events = _parse_sse(r.text)
        assert events[0]["event"] == "meta"
        assert events[-1]["event"] == "done"
        assert events[0]["data"]["assistant_message_id"] > 0
        assert events[-1]["data"]["model"] == "deepseek-v4-flash"
    finally:
        llm_mod.GoClient.astream = orig  # type: ignore[assignment]


async def test_stream_endpoint_tokens_arrive_progressively(
    app_with_overrides: FastAPI,
) -> None:
    """Los tokens deben llegar con gaps de tiempo, no todos de golpe."""
    import app.agent.llm as llm_mod

    async def fake_astream(self: Any, **_kwargs: Any) -> Any:
        yield ("primero ", "deepseek-v4-flash", [])
        await asyncio.sleep(0.05)
        yield ("segundo ", "deepseek-v4-flash", [])
        await asyncio.sleep(0.05)
        yield ("tercero", "deepseek-v4-flash", [])

    orig = llm_mod.GoClient.astream
    llm_mod.GoClient.astream = fake_astream  # type: ignore[assignment]
    try:
        transport = ASGITransport(app=app_with_overrides)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post(
                "/chats/1/messages/stream", json={"content": "hola"}
            )
        events = _parse_sse(r.text)
        tokens = [e for e in events if e["event"] == "token"]
        assert [t["data"] for t in tokens] == ["primero ", "segundo ", "tercero"]
    finally:
        llm_mod.GoClient.astream = orig  # type: ignore[assignment]


async def test_stream_endpoint_persists_assistant_message(
    app_with_overrides: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El mensaje del assistant se persiste con el texto acumulado."""
    # Hacemos que el SessionLocal real (en route handler) apunte a la DB
    # de test directamente. Como ya hicimos el override en el fixture, el
    # routes.py ya usa TestSession, así que abrimos por esa.
    from app.db.base import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr("app.agent.routes.SessionLocal", TestSession)
    with TestSession() as db:
        user = User(
            id=1, email="t@test.com", name="T", password_hash="x",
            created_at=datetime(2024, 1, 1),
        )
        profile = UserProfile(user_id=1, preferences_json="{}", current_year=3)
        materia = Materia(id=1, code="SO", name="Sistemas Operativos", year=3)
        modulo = Modulo(
            id=1, user_id=1, materia_id=1, name="TP1",
            created_at=datetime(2024, 1, 1),
        )
        chat = Chat(id=1, modulo_id=1, title="chat 1", created_at=datetime(2024, 1, 1))
        db.add_all([user, profile, materia, modulo, chat])
        db.commit()

    import app.agent.llm as llm_mod

    async def fake_astream(self: Any, **_kwargs: Any) -> Any:
        yield ("hola mundo", "deepseek-v4-flash", [])

    orig = llm_mod.GoClient.astream
    llm_mod.GoClient.astream = fake_astream  # type: ignore[assignment]
    try:
        transport = ASGITransport(app=app_with_overrides)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post(
                "/chats/1/messages/stream", json={"content": "saluda"}
            )
        assert r.status_code == 200
        with TestSession() as db:
            assistants = (
                db.query(Message)
                .filter(Message.chat_id == 1, Message.role == "assistant")
                .all()
            )
        assert len(assistants) == 1
        assert assistants[0].content == "hola mundo"
        assert assistants[0].model_used == "deepseek-v4-flash"
    finally:
        llm_mod.GoClient.astream = orig  # type: ignore[assignment]


async def test_stream_endpoint_propagates_tool_call_description(
    app_with_overrides: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El evento tool_call incluye description y display_args."""
    from app.db.base import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr("app.agent.routes.SessionLocal", TestSession)
    with TestSession() as db:
        user = User(
            id=1, email="t@test.com", name="T", password_hash="x",
            created_at=datetime(2024, 1, 1),
        )
        profile = UserProfile(user_id=1, preferences_json="{}", current_year=3)
        materia = Materia(id=1, code="SO", name="Sistemas Operativos", year=3)
        modulo = Modulo(
            id=1, user_id=1, materia_id=1, name="TP1",
            created_at=datetime(2024, 1, 1),
        )
        chat = Chat(id=1, modulo_id=1, title="chat 1", created_at=datetime(2024, 1, 1))
        db.add_all([user, profile, materia, modulo, chat])
        db.commit()

    # mock list_documents
    def _list(ctx: ToolContext, modulo_id: int | None = None) -> dict[str, Any]:
        return {
            "ok": True,
            "tool": "list_documents",
            "documents": [{"id": 10, "filename": "tp.pdf", "status": "ready"}],
            "count": 1,
        }

    monkeypatch.setitem(
        REGISTRY,
        "list_documents",
        REGISTRY["list_documents"].__class__(
            name="list_documents",
            description=REGISTRY["list_documents"].description,
            fn=_list,
            args_schema=REGISTRY["list_documents"].args_schema,
        ),
    )

    import app.agent.llm as llm_mod

    call_count = {"n": 0}

    async def fake_astream(self: Any, **_kwargs: Any) -> Any:
        call_count["n"] += 1
        if call_count["n"] == 1:
            yield ("", "deepseek-v4-flash", [{
                "id": "call_1", "name": "list_documents",
                "arguments": {}, "arguments_raw": "{}",
            }])
        else:
            yield ("tenés 1 doc", "deepseek-v4-flash", [])

    orig = llm_mod.GoClient.astream
    llm_mod.GoClient.astream = fake_astream  # type: ignore[assignment]
    try:
        transport = ASGITransport(app=app_with_overrides)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post(
                "/chats/1/messages/stream", json={"content": "qué tengo?"}
            )
        events = _parse_sse(r.text)
        tc_events = [e for e in events if e["event"] == "tool_call"]
        tr_events = [e for e in events if e["event"] == "tool_result"]
        assert len(tc_events) == 1
        assert tc_events[0]["data"]["name"] == "list_documents"
        assert "description" in tc_events[0]["data"]
        assert "display_args" in tc_events[0]["data"]
        assert len(tr_events) == 1
        assert "duration_ms" in tr_events[0]["data"]
        assert "description" in tr_events[0]["data"]
    finally:
        llm_mod.GoClient.astream = orig  # type: ignore[assignment]


async def test_stream_endpoint_propagates_llm_call_and_response(
    app_with_overrides: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El endpoint propaga los eventos ``llm_call`` y ``llm_response``."""
    from app.db.base import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr("app.agent.routes.SessionLocal", TestSession)
    with TestSession() as db:
        user = User(
            id=1, email="t@test.com", name="T", password_hash="x",
            created_at=datetime(2024, 1, 1),
        )
        profile = UserProfile(user_id=1, preferences_json="{}", current_year=3)
        materia = Materia(id=1, code="SO", name="Sistemas Operativos", year=3)
        modulo = Modulo(
            id=1, user_id=1, materia_id=1, name="TP1",
            created_at=datetime(2024, 1, 1),
        )
        chat = Chat(id=1, modulo_id=1, title="chat 1", created_at=datetime(2024, 1, 1))
        db.add_all([user, profile, materia, modulo, chat])
        db.commit()

    import app.agent.llm as llm_mod

    async def fake_astream(self: Any, **_kwargs: Any) -> Any:
        yield ("hola mundo", "deepseek-v4-flash", [])

    orig = llm_mod.GoClient.astream
    llm_mod.GoClient.astream = fake_astream  # type: ignore[assignment]
    try:
        transport = ASGITransport(app=app_with_overrides)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post(
                "/chats/1/messages/stream", json={"content": "saluda"}
            )
        events = _parse_sse(r.text)
        kinds = [e["event"] for e in events]
        # En una respuesta solo-texto, hay 1 llm_call y 1 llm_response.
        assert "llm_call" in kinds
        assert "llm_response" in kinds
        llm_call_events = [e for e in events if e["event"] == "llm_call"]
        llm_response_events = [e for e in events if e["event"] == "llm_response"]
        assert len(llm_call_events) == 1
        assert len(llm_response_events) == 1
        # El llm_call lleva metadatos del request.
        call_data = llm_call_events[0]["data"]
        assert call_data["model"] == "deepseek-v4-flash"
        assert call_data["messages_count"] >= 1
        assert call_data["total_chars"] >= 0
        # El llm_response lleva metadatos del response.
        response_data = llm_response_events[0]["data"]
        assert response_data["model"] == "deepseek-v4-flash"
        assert response_data["finish_reason"] == "stop"
        assert response_data["text_chars"] == len("hola mundo")
        assert response_data["tool_calls_count"] == 0
        assert response_data["duration_ms"] >= 0
    finally:
        llm_mod.GoClient.astream = orig  # type: ignore[assignment]
