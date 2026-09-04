"""Изображения из атласов."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from app.api.deps import CurrentAdmin, DbSession
from app.core.config import settings
from app.models.image import AtlasImage
from app.schemas.common import MessageResponse, Page
from app.schemas.content import ImageOut, ImageUpdate
from app.services import storage
from app.worker.queue import enqueue

router = APIRouter(prefix="/images", tags=["Изображения атласов"])


def _to_out(image: AtlasImage) -> ImageOut:
    data = ImageOut.model_validate(image)
    data.is_indexed = image.embedding is not None
    return data


def _parse_list(raw: str | None) -> list[str] | None:
    """Списки структур приходят из формы либо JSON-массивом, либо через запятую."""
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            return [str(x).strip() for x in parsed if str(x).strip()]
        except json.JSONDecodeError:
            pass
    return [part.strip() for part in raw.split(",") if part.strip()] or None


@router.get("", response_model=Page[ImageOut])
async def list_images(
    db: DbSession,
    _: CurrentAdmin,
    page: int = Query(1, ge=1),
    size: int = Query(24, ge=1, le=200),
    section: str | None = None,
    search: str | None = None,
) -> Page[ImageOut]:
    query = select(AtlasImage)
    count_query = select(func.count(AtlasImage.id))

    conditions = []
    if section:
        conditions.append(AtlasImage.section == section)
    if search:
        conditions.append(AtlasImage.title.ilike(f"%{search}%"))

    for condition in conditions:
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = (await db.execute(count_query)).scalar_one()
    rows = (
        await db.execute(
            query.order_by(AtlasImage.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    ).scalars().all()

    return Page[ImageOut](
        items=[_to_out(row) for row in rows], total=total, page=page, size=size
    )


@router.post("", response_model=ImageOut, status_code=status.HTTP_201_CREATED)
async def upload_image(
    db: DbSession,
    _: CurrentAdmin,
    file: UploadFile = File(...),
    title: str = Form(...),
    description: str | None = Form(None),
    structures_ru: str | None = Form(None),
    structures_lat: str | None = Form(None),
    section: str | None = Form(None),
    source_title: str | None = Form(None),
    source_authors: str | None = Form(None),
    source_page: int | None = Form(None),
    license_note: str | None = Form(None),
) -> ImageOut:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in storage.ALLOWED_IMAGE_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail="Поддерживаются форматы: " + ", ".join(sorted(storage.ALLOWED_IMAGE_SUFFIXES)),
        )

    stored_path, content_hash, size_bytes = storage.save_upload(
        file.file, file.filename or "image", storage.IMAGES_DIR
    )

    if size_bytes > settings.max_upload_size_mb * 1024 * 1024:
        storage.delete_file(stored_path)
        raise HTTPException(status_code=413, detail="Файл слишком большой")

    duplicate = (
        await db.execute(select(AtlasImage).where(AtlasImage.content_hash == content_hash))
    ).scalar_one_or_none()
    if duplicate is not None:
        raise HTTPException(
            status_code=409, detail=f"Изображение уже загружено (id {duplicate.id})"
        )

    dimensions = storage.image_size(stored_path)
    thumbnail = storage.make_thumbnail(stored_path)

    image = AtlasImage(
        title=title,
        description=description,
        structures_ru=_parse_list(structures_ru),
        structures_lat=_parse_list(structures_lat),
        section=section,
        source_title=source_title,
        source_authors=source_authors,
        source_page=source_page,
        license_note=license_note,
        original_filename=file.filename or "image",
        stored_path=str(stored_path),
        thumbnail_path=str(thumbnail) if thumbnail else None,
        mime_type=file.content_type,
        size_bytes=size_bytes,
        content_hash=content_hash,
        width=dimensions[0] if dimensions else None,
        height=dimensions[1] if dimensions else None,
    )
    db.add(image)
    await db.commit()
    await db.refresh(image)

    await enqueue("index_image", image.id)
    return _to_out(image)


@router.patch("/{image_id}", response_model=ImageOut)
async def update_image(
    image_id: int, payload: ImageUpdate, db: DbSession, _: CurrentAdmin
) -> ImageOut:
    image = await db.get(AtlasImage, image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="Изображение не найдено")

    changed = payload.model_dump(exclude_unset=True)
    for field, value in changed.items():
        setattr(image, field, value)
    await db.commit()
    await db.refresh(image)

    # Описание и перечень структур — это то, по чему изображение ищется,
    # поэтому после их правки нужен новый вектор
    if {"title", "description", "structures_ru", "structures_lat", "section"} & set(changed):
        await enqueue("index_image", image_id)

    return _to_out(image)


@router.get("/{image_id}/file")
async def get_image_file(
    image_id: int, db: DbSession, thumbnail: bool = False
) -> FileResponse:
    """Отдаётся без авторизации: ссылки на картинки уходят студентам в VK."""
    image = await db.get(AtlasImage, image_id)
    if image is None or not image.is_active:
        raise HTTPException(status_code=404, detail="Изображение не найдено")

    path = Path(image.thumbnail_path or image.stored_path) if thumbnail else Path(image.stored_path)
    if not path.exists():
        path = Path(image.stored_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл отсутствует в хранилище")

    return FileResponse(path, media_type=image.mime_type or "image/jpeg")


@router.post("/reindex", response_model=MessageResponse)
async def reindex_images(db: DbSession, _: CurrentAdmin) -> MessageResponse:
    ids = (await db.execute(select(AtlasImage.id))).scalars().all()
    for image_id in ids:
        await enqueue("index_image", image_id)
    return MessageResponse(detail=f"В очередь поставлено изображений: {len(ids)}")


@router.delete("/{image_id}", response_model=MessageResponse)
async def delete_image(image_id: int, db: DbSession, _: CurrentAdmin) -> MessageResponse:
    image = await db.get(AtlasImage, image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="Изображение не найдено")

    stored_path, thumbnail_path = image.stored_path, image.thumbnail_path
    await db.delete(image)
    await db.commit()

    storage.delete_file(stored_path)
    if thumbnail_path:
        storage.delete_file(thumbnail_path)

    return MessageResponse(detail="Изображение удалено")
