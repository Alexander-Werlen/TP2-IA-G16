"""Tests para ``read_document`` y la detección de secciones.

Mockeamos la DB para no depender de SQLite/Chroma. Cubrimos:

  - Truncado al cap con corte "prolijo" (no rompe párrafos).
  - Detección de headings en español: "Sección N", "Capítulo N", "Anexo X",
    numeración decimal, romanos, MAYÚSCULAS cortas.
  - Output con ``first_section_seen``, ``last_section_seen``,
    ``sections_in_returned`` y ``sections_omitted``.
  - Cuando NO se trunca, ``sections_omitted`` va vacía.
  - Documento sin headings reconocibles: todos los campos de sección
    en ``None``/``[]``.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.agent.tools import documents
from app.agent.tools.context import ToolContext
from app.agent.tools.documents import (
    _detect_sections,
    _smart_truncate,
    read_document,
)


# ── Helpers de fake DB ──────────────────────────────────────────
def _make_ctx(user_id: int = 1) -> ToolContext:
    return ToolContext(
        user_id=user_id,
        materia_id=1,
        materia_name="X",
        modulo_name="M",
        chat_id=1,
    )


def _make_doc(doc_id: int, status: str = "ready") -> Any:
    return SimpleNamespace(
        id=doc_id,
        modulo=SimpleNamespace(user_id=1),
        status=status,
        filename=f"doc{doc_id}.pdf",
        mime="application/pdf",
    )


def _make_chunks(parts: list[str]) -> list[Any]:
    return [SimpleNamespace(text=p, chunk_index=i) for i, p in enumerate(parts)]


class FakeSession:
    def __init__(self, doc: Any, chunks: list[Any]) -> None:
        self._doc = doc
        self._chunks = chunks

    def get(self, model: Any, pk: int) -> Any:
        return self._doc

    def execute(self, stmt: Any) -> Any:
        class _R:
            def __init__(self, rows: list[Any]) -> None:
                self._rows = rows

            def scalars(self) -> _R:
                return self

            def all(self) -> list[Any]:
                return self._rows

        return _R(self._chunks)

    def close(self) -> None:
        pass


def _install_session(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    """Mockea SessionLocal para devolver un doc + un chunk con ``text``."""
    session = FakeSession(_make_doc(1), _make_chunks([text]))
    monkeypatch.setattr(documents, "SessionLocal", lambda: session)


# ── Tests de helpers ────────────────────────────────────────────
class TestDetectSections:
    def test_detects_spanish_section_headers(self) -> None:
        text = (
            "Intro\n\n"
            "Sección 1 - Marco Teórico\n\n"
            "bla bla\n\n"
            "Sección 2 - Desarrollo\n\n"
            "bla bla\n\n"
            "Sección 3 - Conclusiones\n"
        )
        result = _detect_sections(text)
        assert result == [
            "Sección 1 - Marco Teórico",
            "Sección 2 - Desarrollo",
            "Sección 3 - Conclusiones",
        ]

    def test_detects_capitulo_and_anexo(self) -> None:
        text = (
            "Capítulo 1: Introducción\n\n"
            "bla\n\n"
            "Capítulo 2: Métodos\n\n"
            "bla\n\n"
            "Anexo A - Datos extra\n"
        )
        result = _detect_sections(text)
        assert result == [
            "Capítulo 1: Introducción",
            "Capítulo 2: Métodos",
            "Anexo A - Datos extra",
        ]

    def test_detects_decimal_numbering(self) -> None:
        text = (
            "1. Introducción\n\n"
            "bla\n\n"
            "2.1 Subtema\n\n"
            "bla\n\n"
            "3.4.5 Detalle\n"
        )
        result = _detect_sections(text)
        assert "1. Introducción" in result
        assert "2.1 Subtema" in result
        assert "3.4.5 Detalle" in result

    def test_deduplicates_repeated_headings(self) -> None:
        text = (
            "Sección 1 - A\n\n"
            "bla\n\n"
            "Sección 1 - A\n\n"
            "bla\n\n"
            "Sección 2 - B\n"
        )
        result = _detect_sections(text)
        assert result.count("Sección 1 - A") == 1
        assert result.count("Sección 2 - B") == 1

    def test_returns_empty_for_plain_text(self) -> None:
        text = "lorem ipsum dolor sit amet " * 100
        assert _detect_sections(text) == []

    def test_ignores_short_uppercase_in_middle_of_paragraph(self) -> None:
        text = "En el medio del texto aparece RAG como sigla y sigue.\n\nOtra cosa."
        assert _detect_sections(text) == []


class TestSmartTruncate:
    def test_returns_full_text_when_under_cap(self) -> None:
        text = "hola mundo\n\nsegundo párrafo"
        assert _smart_truncate(text, cap=100) == text

    def test_cuts_at_paragraph_boundary(self) -> None:
        text = "párrafo 1\n\npárrafo 2\n\npárrafo 3"
        result = _smart_truncate(text, cap=25)
        # Con cap=25 hay un \n\n en posición 10 (=cap/2) y otro en 20 (>cap/2).
        # La heurística toma el último \n\n antes del cap.
        assert result == "párrafo 1\n\npárrafo 2"
        assert "párrafo 3" not in result

    def test_cuts_at_whitespace_if_no_paragraph_break(self) -> None:
        text = "una sola línea muy larga " * 50
        result = _smart_truncate(text, cap=100)
        assert not result.endswith(" ")
        assert len(result) <= 100

    def test_raw_cut_if_no_good_boundary(self) -> None:
        text = "a" * 200
        result = _smart_truncate(text, cap=50)
        assert result == "a" * 50


# ── Tests de read_document ──────────────────────────────────────
class TestReadDocument:
    def test_returns_full_text_when_under_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        text = (
            "1. Introducción\n\n"
            "Contenido corto de prueba.\n\n"
            "2. Conclusiones\n\n"
            "Más contenido."
        )
        _install_session(monkeypatch, text)

        result = read_document(_make_ctx(), document_id=1)

        assert result["ok"] is True
        assert result["truncated"] is False
        assert result["total_chars"] == len(text)
        assert result["returned_chars"] == len(text)
        assert result["first_section_seen"] == "1. Introducción"
        assert result["last_section_seen"] == "2. Conclusiones"
        assert result["sections_omitted"] == []
        assert "1. Introducción" in result["sections_in_returned"]
        assert "2. Conclusiones" in result["sections_in_returned"]

    def test_truncates_and_reports_omitted_sections(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Padding MUY grande para que solo la 1ra sección entre en cap=1500.
        parts: list[str] = []
        for i in range(1, 6):
            section = f"Sección {i} - Contenido de la sección número {i}\n\n"
            padding = "bla bla bla " * 500
            parts.append(section + padding + "\n\n")
        full_text = "".join(parts)
        _install_session(monkeypatch, full_text)

        result = read_document(_make_ctx(), document_id=1, max_chars=1500)

        assert result["ok"] is True
        assert result["truncated"] is True
        assert result["total_chars"] == len(full_text)
        assert result["returned_chars"] <= 1500
        assert result["first_section_seen"] == (
            "Sección 1 - Contenido de la sección número 1"
        )
        # Con cap chico, solo entra la 1ra sección.
        assert result["sections_in_returned"] == [
            "Sección 1 - Contenido de la sección número 1"
        ]
        # Las secciones 2..5 quedan omitidas.
        assert len(result["sections_omitted"]) == 4
        omitted_text = " ".join(result["sections_omitted"])
        assert "Sección 2" in omitted_text
        assert "Sección 3" in omitted_text
        assert "Sección 4" in omitted_text
        assert "Sección 5" in omitted_text

    def test_default_cap_is_200k(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 60k chars: pasaba el cap viejo (50k) pero no el nuevo (200k).
        text = "Sección Única\n\n" + ("lorem ipsum " * 6000)
        _install_session(monkeypatch, text)

        result = read_document(_make_ctx(), document_id=1)

        assert result["ok"] is True
        assert result["truncated"] is False
        assert result["total_chars"] == len(text)
        assert result["returned_chars"] == len(text)
        assert "Sección Única" in result["sections_in_returned"]

    def test_handles_document_without_headings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        text = "lorem ipsum dolor sit amet " * 100
        _install_session(monkeypatch, text)

        result = read_document(_make_ctx(), document_id=1)

        assert result["ok"] is True
        assert result["first_section_seen"] is None
        assert result["last_section_seen"] is None
        assert result["sections_in_returned"] == []
        assert result["sections_omitted"] == []

    def test_rejects_zero_or_negative_max_chars(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_session(monkeypatch, "x" * 1000)

        result = read_document(_make_ctx(), document_id=1, max_chars=0)
        assert result["ok"] is False
        assert "positivo" in result["error"]

        result = read_document(_make_ctx(), document_id=1, max_chars=-5)
        assert result["ok"] is False
        assert "positivo" in result["error"]

    def test_clamps_max_chars_above_absolute_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        text = "x" * 1000
        _install_session(monkeypatch, text)

        result = read_document(_make_ctx(), document_id=1, max_chars=1_000_000)
        assert result["ok"] is True
        assert result["truncated"] is False
        assert result["returned_chars"] == 1000
