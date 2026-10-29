"""Управление расписаниями групп и списком преподавателей."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentAdmin, DbSession
from app.models.organization import GroupSchedule, Teacher
from app.schemas.common import MessageResponse
from app.schemas.organization import GroupScheduleOut, TeacherCreate, TeacherOut, TeacherUpdate
from app.services import storage

router = APIRouter(prefix="/organization", tags=["Организационная информация"])

SCHEDULES_DIR = "schedules"
MAX_SCHEDULE_SIZE = 20 * 1024 * 1024
IMAGE_SUFFIXES = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
SCHEDULE_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}


@router.get("/schedules", response_model=list[GroupScheduleOut])
async def list_schedules(db: DbSession, _: CurrentAdmin) -> list[GroupSchedule]:
    return list(
        (
            await db.execute(
                select(GroupSchedule)
                .where(GroupSchedule.is_active.is_(True))
                .order_by(GroupSchedule.group_name)
            )
        ).scalars().all()
    )


@router.post(
    "/schedules", response_model=GroupScheduleOut, status_code=status.HTTP_201_CREATED
)
async def upload_schedule(
    db: DbSession,
    _: CurrentAdmin,
    group_name: str = Form(..., min_length=1, max_length=40),
    file: UploadFile = File(...),
) -> GroupSchedule:
    group_name = group_name.strip()
    if not group_name:
        raise HTTPException(status_code=422, detail="Укажите учебную группу")
    if file.size is not None and file.size > MAX_SCHEDULE_SIZE:
        raise HTTPException(status_code=413, detail="Файл расписания больше 20 МБ")

    source_suffix = Path(file.filename or "").suffix.lower()
    image_format: str | None = None
    if source_suffix == ".pdf":
        header = await file.read(5)
        await file.seek(0)
        if header != b"%PDF-":
            raise HTTPException(status_code=400, detail="Файл не является корректным PDF")
        suffix = ".pdf"
    else:
        try:
            from PIL import Image, UnidentifiedImageError

            image = Image.open(file.file)
            image_format = image.format
            image.verify()
        except (OSError, UnidentifiedImageError) as exc:
            raise HTTPException(
                status_code=400,
                detail="Загрузите изображение JPEG, PNG, WebP или PDF",
            ) from exc
        finally:
            await file.seek(0)

        suffix = IMAGE_SUFFIXES.get(image_format or "")
        if suffix is None:
            raise HTTPException(
                status_code=400,
                detail="Поддерживаются только JPEG, PNG, WebP и PDF",
            )
    if file.size is None:
        content = await file.read(MAX_SCHEDULE_SIZE + 1)
        await file.seek(0)
        if len(content) > MAX_SCHEDULE_SIZE:
            raise HTTPException(status_code=413, detail="Файл расписания больше 20 МБ")

    filename = f"{Path(file.filename or 'schedule').stem}{suffix}"
    mime_type = SCHEDULE_MIME_TYPES[suffix]
    path, _, size_bytes = storage.save_upload(file.file, filename, SCHEDULES_DIR)
    old_path: str | None = None
    schedule = (
        await db.execute(
            select(GroupSchedule).where(
                func.lower(GroupSchedule.group_name) == group_name.casefold()
            )
        )
    ).scalar_one_or_none()

    if schedule is None:
        schedule = GroupSchedule(
            group_name=group_name,
            stored_path=str(path),
            original_filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
        )
        db.add(schedule)
    else:
        old_path = schedule.stored_path
        schedule.group_name = group_name
        schedule.stored_path = str(path)
        schedule.original_filename = filename
        schedule.mime_type = mime_type
        schedule.size_bytes = size_bytes
        schedule.vk_attachment_id = None
        schedule.is_active = True

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if old_path != str(path):
            storage.delete_file(path)
        raise HTTPException(status_code=409, detail="Расписание этой группы уже изменено") from exc

    if old_path and old_path != str(path):
        storage.delete_file(old_path)
    await db.refresh(schedule)
    return schedule


@router.delete("/schedules/{schedule_id}", response_model=MessageResponse)
async def delete_schedule(
    schedule_id: int, db: DbSession, _: CurrentAdmin
) -> MessageResponse:
    schedule = await db.get(GroupSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Расписание не найдено")
    path = schedule.stored_path
    await db.delete(schedule)
    await db.commit()
    storage.delete_file(path)
    return MessageResponse(detail="Расписание удалено")


@router.get("/teachers", response_model=list[TeacherOut])
async def list_teachers(db: DbSession, _: CurrentAdmin) -> list[Teacher]:
    return list(
        (
            await db.execute(
                select(Teacher)
                .where(Teacher.is_active.is_(True))
                .order_by(Teacher.full_name, Teacher.id)
            )
        ).scalars().all()
    )


@router.post("/teachers", response_model=TeacherOut, status_code=status.HTTP_201_CREATED)
async def create_teacher(
    payload: TeacherCreate, db: DbSession, _: CurrentAdmin
) -> Teacher:
    teacher = Teacher(**payload.model_dump())
    db.add(teacher)
    await db.commit()
    await db.refresh(teacher)
    return teacher


@router.patch("/teachers/{teacher_id}", response_model=TeacherOut)
async def update_teacher(
    teacher_id: int,
    payload: TeacherUpdate,
    db: DbSession,
    _: CurrentAdmin,
) -> Teacher:
    teacher = await db.get(Teacher, teacher_id)
    if teacher is None:
        raise HTTPException(status_code=404, detail="Преподаватель не найден")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(teacher, field, value)
    await db.commit()
    await db.refresh(teacher)
    return teacher


@router.delete("/teachers/{teacher_id}", response_model=MessageResponse)
async def delete_teacher(
    teacher_id: int, db: DbSession, _: CurrentAdmin
) -> MessageResponse:
    teacher = await db.get(Teacher, teacher_id)
    if teacher is None:
        raise HTTPException(status_code=404, detail="Преподаватель не найден")
    await db.delete(teacher)
    await db.commit()
    return MessageResponse(detail="Преподаватель удалён")