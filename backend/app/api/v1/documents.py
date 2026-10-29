"""Загрузка и управление учебными материалами."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from app.api.deps import CurrentAdmin, DbSession
from app.core.config import settings
from app.core.logging import get_logger
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.schemas.common import MessageResponse, Page
from app.schemas.content import ChunkOut, DocumentOut, DocumentUpdate
from app.services import document_service, storage
from app.worker.queue import enqueue, has_document_jobs

log = get_logger(__name__)
router = APIRouter(prefix="/documents", tags=["Учебные материалы"])


@router.get("", response_model=Page[DocumentOut])
async def list_documents(
    db: DbSession,
    _: CurrentAdmin,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    status_filter: DocumentStatus | None = Query(None, alias="status"),
    section: str | None = None,
    search: str | None = None,
) -> Page[DocumentOut]:
    query = select(Document)
    count_query = select(func.count(Document.id))

    conditions = []
    if status_filter:
        conditions.append(Document.status == status_filter)
    if section:
        conditions.append(Document.section == section)
    if search:
        conditions.append(Document.title.ilike(f"%{search}%"))

    for condition in conditions:
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = (await db.execute(count_query)).scalar_one()
    rows = (
        await db.execute(
            query.order_by(Document.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    ).scalars().all()

    return Page[DocumentOut](
        items=[DocumentOut.model_validate(row) for row in rows],
        total=total,
        page=page,
        size=size,
    )


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    db: DbSession,
    _: CurrentAdmin,
    file: UploadFile = File(...),
    title: str = Form(...),
    authors: str | None = Form(None),
    edition: str | None = Form(None),
    year: int | None = Form(None),
    section: str | None = Form(None),
) -> Document:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in storage.ALLOWED_DOCUMENT_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Поддерживаются форматы: "
                + ", ".join(sorted(storage.ALLOWED_DOCUMENT_SUFFIXES))
            ),
        )

    stored_path, content_hash, size_bytes = storage.save_upload(
        file.file, file.filename or "document", storage.DOCUMENTS_DIR
    )

    if size_bytes > settings.max_upload_size_mb * 1024 * 1024:
        storage.delete_file(stored_path)
        raise HTTPException(
            status_code=413,
            detail=f"Файл больше допустимых {settings.max_upload_size_mb} МБ",
        )

    duplicate = (
        await db.execute(select(Document).where(Document.content_hash == content_hash))
    ).scalar_one_or_none()
    if duplicate is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Такой файл уже загружен: «{duplicate.title}» (id {duplicate.id})",
        )

    document = Document(
        title=title,
        authors=authors,
        edition=edition,
        year=year,
        section=section,
        original_filename=file.filename or "document",
        stored_path=str(stored_path),
        mime_type=file.content_type,
        size_bytes=size_bytes,
        content_hash=content_hash,
        status=DocumentStatus.pending,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    await enqueue("index_document", document.id)
    log.info("document_uploaded", document_id=document.id, title=title)

    return document


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(document_id: int, db: DbSession, _: CurrentAdmin) -> Document:
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Документ не найден")
    return document


@router.patch("/{document_id}", response_model=DocumentOut)
async def update_document(
    document_id: int, payload: DocumentUpdate, db: DbSession, _: CurrentAdmin
) -> Document:
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Документ не найден")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(document, field, value)

    await db.commit()
    await db.refresh(document)
    return document


@router.post("/{document_id}/reindex", response_model=MessageResponse)
async def reindex_document(document_id: int, db: DbSession, _: CurrentAdmin) -> MessageResponse:
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Документ не найден")

    if await has_document_jobs(document_id):
        return MessageResponse(detail="Документ уже стоит в очереди или обрабатывается")

    document.status = DocumentStatus.pending
    document.progress = 0
    document.error_message = None
    await db.commit()

    await enqueue("index_document", document_id)
    return MessageResponse(detail="Документ поставлен в очередь на переиндексацию")


@router.get("/{document_id}/chunks", response_model=Page[ChunkOut])
async def list_chunks(
    document_id: int,
    db: DbSession,
    _: CurrentAdmin,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> Page[ChunkOut]:
    total = (
        await db.execute(
            select(func.count(DocumentChunk.id)).where(
                DocumentChunk.document_id == document_id
            )
        )
    ).scalar_one()

    rows = (
        await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
            .offset((page - 1) * size)
            .limit(size)
        )
    ).scalars().all()

    return Page[ChunkOut](
        items=[ChunkOut.model_validate(row) for row in rows],
        total=total,
        page=page,
        size=size,
    )


@router.get("/{document_id}/file")
async def download_document(document_id: int, db: DbSession, _: CurrentAdmin) -> FileResponse:
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Документ не найден")

    path = Path(document.stored_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл отсутствует в хранилище")

    return FileResponse(
        path, filename=document.original_filename, media_type=document.mime_type
    )


@router.delete("/{document_id}", response_model=MessageResponse)
async def delete_document(document_id: int, db: DbSession, _: CurrentAdmin) -> MessageResponse:
    if not await document_service.delete_document(db, document_id):
        raise HTTPException(status_code=404, detail="Документ не найден")
    return MessageResponse(detail="Документ и его фрагменты удалены")


@router.get("/meta/sections", response_model=list[str])
async def list_sections(db: DbSession, _: CurrentAdmin) -> list[str]:
    rows = (
        await db.execute(
            select(Document.section)
            .where(Document.section.is_not(None))
            .distinct()
            .order_by(Document.section)
        )
    ).scalars().all()
    return list(rows)
