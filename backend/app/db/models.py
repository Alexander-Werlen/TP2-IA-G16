"""SQLAlchemy ORM models for TutorIA (Fase 1 + Fase 2).

Las tablas se descubren automáticamente vía `Base.metadata` desde Alembic.
Importar este módulo (o sus modelos) en `app/main.py` al inicio para
asegurarse de que el metadata esté poblado antes de correr migraciones.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    profile: Mapped[UserProfile | None] = relationship(
        "UserProfile", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    career: Mapped[str] = mapped_column(String(255), nullable=False, default="Ing. en Sistemas")
    current_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preferences_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    user: Mapped[User] = relationship("User", back_populates="profile")

    def __repr__(self) -> str:
        return f"<UserProfile user_id={self.user_id} career={self.career!r}>"


class Materia(Base):
    __tablename__ = "materias"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<Materia id={self.id} code={self.code!r} year={self.year}>"


class Modulo(Base):
    __tablename__ = "modulos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    materia_id: Mapped[int] = mapped_column(
        ForeignKey("materias.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    user: Mapped[User] = relationship("User")
    materia: Mapped[Materia] = relationship("Materia")
    chats: Mapped[list[Chat]] = relationship(
        "Chat", back_populates="modulo", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Modulo id={self.id} user_id={self.user_id} materia_id={self.materia_id} name={self.name!r}>"


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    modulo_id: Mapped[int] = mapped_column(
        ForeignKey("modulos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    modulo: Mapped[Modulo] = relationship("Modulo", back_populates="chats")
    messages: Mapped[list[Message]] = relationship(
        "Message", back_populates="chat", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Chat id={self.id} modulo_id={self.modulo_id} title={self.title!r}>"


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    chat: Mapped[Chat] = relationship("Chat", back_populates="messages")

    def __repr__(self) -> str:
        return f"<Message id={self.id} chat_id={self.chat_id} role={self.role!r}>"


# ── Fase 4: documents y document_chunks ───────────────────
DOCUMENT_STATUSES = ("processing", "ready", "error")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    modulo_id: Mapped[int] = mapped_column(
        ForeignKey("modulos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    materia_id: Mapped[int] = mapped_column(
        ForeignKey("materias.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime: Mapped[str] = mapped_column(String(128), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="processing"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    modulo: Mapped[Modulo] = relationship("Modulo")
    materia: Mapped[Materia] = relationship("Materia")
    chunks: Mapped[list[DocumentChunk]] = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Document id={self.id} modulo_id={self.modulo_id} "
            f"filename={self.filename!r} status={self.status!r}>"
        )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    document: Mapped[Document] = relationship("Document", back_populates="chunks")

    def __repr__(self) -> str:
        return (
            f"<DocumentChunk id={self.id} document_id={self.document_id} "
            f"index={self.chunk_index}>"
        )


# ── Fase 6: events (parciales, entregas, finales, etc.) ─────
EVENT_TYPES: tuple[str, ...] = (
    "parcial",
    "recuperatorio",
    "final",
    "entrega",
    "exposicion",
    "otro",
)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    materia_id: Mapped[int | None] = mapped_column(
        ForeignKey("materias.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    materia: Mapped[Materia | None] = relationship("Materia")

    def __repr__(self) -> str:
        return (
            f"<Event id={self.id} user_id={self.user_id} type={self.type!r} "
            f"date={self.date.isoformat()!r}>"
        )
