"""Documents router (Fase 4).

Endpoints:
- ``POST   /modulos/{modulo_id}/documents``    multipart upload. Crea el
  registro en estado ``processing`` y agenda el pipeline (parseo +
  chunking + resumen) en un ``BackgroundTask``. Devuelve ``201`` con el
  documento.
- ``GET    /modulos/{modulo_id}/documents``    lista los documentos del
  módulo del usuario autenticado.
- ``GET    /documents/{document_id}``          detalle (incluye ``summary``
  y ``status``). El frontend usa esto para el polling de procesamiento.
- ``DELETE /documents/{document_id}``          borra el doc + chunks +
  archivo físico. Sólo el dueño.

Todos los endpoints requieren JWT y validan ownership transitivo
(documento → módulo → user).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import rag
from app.auth.deps import get_current_user
from app.config import get_settings
from app.db.models import Document, Modulo, User
from app.db.session import get_db
from app.documents.parser import ACCEPTED_MIMES, is_accepted_mime
from app.documents.processing import process_document, remove_file_for_user
from app.schemas.document import DocumentListOut, DocumentOut, DocumentStatusOut

logger = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])


# ── helpers ────────────────────────────────────────────────
def _get_owned_modulo(db: Session, modulo_id: int, user: User) -> Modulo:
    modulo = db.get(Modulo, modulo_id)
    if modulo is None or modulo.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Módulo no encontrado",
        )
    return modulo


def _get_owned_document(db: Session, document_id: int, user: User) -> Document:
    doc = db.get(Document, document_id)
    if doc is None or doc.modulo.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Documento no encontrado",
        )
    return doc


def _doc_to_out(d: Document) -> DocumentOut:
    return DocumentOut(
        id=d.id,
        modulo_id=d.modulo_id,
        materia_id=d.materia_id,
        filename=d.filename,
        mime=d.mime,
        size=d.size,
        summary=d.summary,
        summary_model=d.summary_model,
        status=d.status,
        error_message=d.error_message,
        created_at=d.created_at,
    )


# ── POST upload ────────────────────────────────────────────
@router.post(
    "/modulos/{modulo_id}/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
)
def upload_document(
    modulo_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentOut:
    """Sube un archivo, lo registra y dispara el procesamiento async."""
    settings = get_settings()
    modulo = _get_owned_modulo(db, modulo_id, current_user)

    # 1) validar MIME antes de leer nada (evita gastar bandwidth en PDFs
    # que no son PDFs, etc.).
    mime = (file.content_type or "").lower()
    if not is_accepted_mime(mime):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Tipo de archivo no soportado: {mime or 'desconocido'}. "
                f"Aceptados: {', '.join(ACCEPTED_MIMES)}"
            ),
        )

    # 2) leer contenido con tope de tamaño (lectura sync: el repo
    # también es sync y mantiene la coherencia con el resto de rutas).
    content = _read_with_limit(file, settings.max_upload_bytes)

    # 3) crear el documento en estado 'processing'.
    doc = Document(
        modulo_id=modulo.id,
        materia_id=modulo.materia_id,
        filename=file.filename or "documento",
        mime=mime,
        size=len(content),
        status="processing",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    document_id = doc.id

    # 4) agendar el pipeline. La sesión `db` se cierra al salir del
    # handler; el background task abre la suya propia.
    background_tasks.add_task(
        process_document,
        document_id=document_id,
        modulo_id=modulo.id,
        user_id=current_user.id,
        filename=file.filename or "documento",
        content=content,
    )

    logger.info(
        "documents.upload accepted document_id=%s user_id=%s modulo_id=%s "
        "filename=%s size=%d mime=%s",
        document_id,
        current_user.id,
        modulo.id,
        file.filename,
        len(content),
        mime,
    )

    return _doc_to_out(doc)


# ── GET list ───────────────────────────────────────────────
@router.get(
    "/modulos/{modulo_id}/documents",
    response_model=DocumentListOut,
)
def list_documents(
    modulo_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentListOut:
    _get_owned_modulo(db, modulo_id, current_user)
    rows = (
        db.execute(
            select(Document)
            .where(Document.modulo_id == modulo_id)
            .order_by(Document.created_at.desc(), Document.id.desc())
        )
        .scalars()
        .all()
    )
    return DocumentListOut(items=[_doc_to_out(d) for d in rows])


# ── GET detail (polling-friendly) ──────────────────────────
@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentOut:
    doc = _get_owned_document(db, document_id, current_user)
    return _doc_to_out(doc)


# ── GET status snapshot (liviano, ideal para polling) ──────
@router.get("/documents/{document_id}/status", response_model=DocumentStatusOut)
def get_document_status(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentStatusOut:
    doc = _get_owned_document(db, document_id, current_user)
    return DocumentStatusOut(
        id=doc.id,
        status=doc.status,
        summary=doc.summary,
        error_message=doc.error_message,
    )


# ── DELETE ─────────────────────────────────────────────────
@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    doc = _get_owned_document(db, document_id, current_user)
    user_id = current_user.id
    # Persistimos filename/modulo_id antes del delete para logging.
    log_filename = doc.filename
    # Borramos primero de Chroma (best-effort: si falla, igual borramos
    # la fila; queda stale data en Chroma hasta que se reindexe).
    try:
        rag.delete_document_chunks(document_id=document_id)
    except Exception:  # noqa: BLE001
        logger.exception(
            "documents.delete: rag.delete_document_chunks falló document_id=%s", document_id
        )
    # Borramos primero el archivo físico (best-effort) y después la fila.
    # El cascade ORM se encarga de los chunks.
    db.delete(doc)
    db.commit()
    # El archivo fue escrito en <upload_dir>/user_<id>/<doc_id>__<safe>;
    # como la convención usa el id del doc, podemos reconstruir el nombre.
    from app.documents.processing import _safe_filename, _user_upload_dir

    target = _user_upload_dir(user_id) / f"{document_id}__{_safe_filename(log_filename)}"
    remove_file_for_user(user_id, target)
    logger.info(
        "documents.delete document_id=%s user_id=%s filename=%s",
        document_id,
        user_id,
        log_filename,
    )


# ── reader con tope ────────────────────────────────────────
def _read_with_limit(file: UploadFile, max_bytes: int) -> bytes:
    """Lee ``file`` (sync) y aborta con 413 si supera ``max_bytes``."""
    chunks: list[bytes] = []
    total = 0
    chunk_size = 1024 * 1024  # 1 MB
    while True:
        # `file.file` es un SpooledTemporaryFile; lectura sync.
        chunk = file.file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            file.file.close()
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"El archivo supera el máximo permitido "
                    f"({max_bytes // (1024 * 1024)} MB)"
                ),
            )
        chunks.append(chunk)
    return b"".join(chunks)
