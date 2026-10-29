"""Обработка сообщений от студентов во ВКонтакте."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path

import redis.asyncio as aioredis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.chat import Channel
from app.models.figure import DocumentFigure
from app.models.organization import GroupSchedule, Teacher
from app.models.user import VkUser
from app.services import chat_service, figure_service, settings_service
from app.vk.api import VkApi

log = get_logger(__name__)

# Ограничение VK на длину сообщения — режем с запасом
MAX_MESSAGE_LENGTH = 4000

RATE_LIMITED = (
    "Слишком много запросов подряд. Подождите минуту, пожалуйста — "
    "я обрабатываю вопросы по очереди."
)

# VK показывает «печатает» секунд на 10 — на генерации в минуту и дольше
# (локальная модель на CPU) индикатор нужно обновлять самим
TYPING_REFRESH_SECONDS = 8
MENU_STATE_TTL_SECONDS = 1800
MENU_MAIN = [["Чат"], ["Орг. информация"]]
MENU_ORGANIZATION = [["Расписание"], ["Преподаватели"], ["Главное меню"]]
SCHEDULE_PAGE_SIZE = 16


async def _keep_typing(vk_api: VkApi, peer_id: int) -> None:
    while True:
        await vk_api.set_typing(peer_id)
        await asyncio.sleep(TYPING_REFRESH_SECONDS)


async def check_rate_limit(redis: aioredis.Redis, vk_id: int, limit: int) -> bool:
    """Скользящее окно в минуту на пользователя.

    Ограничение нужно не столько от злоупотреблений, сколько от очереди
    к локальной модели: одна карта обслуживает всех студентов сразу.
    """
    key = f"vk:rate:{vk_id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 60)
    return count <= limit


async def get_or_create_user(db: AsyncSession, vk_api: VkApi, vk_id: int) -> VkUser:
    user = (
        await db.execute(select(VkUser).where(VkUser.vk_id == vk_id))
    ).scalar_one_or_none()

    if user is not None:
        return user

    # Имя запрашиваем только при первом обращении
    profiles = await vk_api.get_users([vk_id])
    profile = profiles[0] if profiles else {}

    user = VkUser(
        vk_id=vk_id,
        first_name=profile.get("first_name"),
        last_name=profile.get("last_name"),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    log.info("vk_user_created", vk_id=vk_id)
    return user


def split_message(text: str) -> list[str]:
    """Разбивает длинный ответ по абзацам, не разрывая слова."""
    if len(text) <= MAX_MESSAGE_LENGTH:
        return [text]

    parts: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= MAX_MESSAGE_LENGTH:
            current = candidate
            continue

        if current:
            parts.append(current)
        # Абзац сам длиннее лимита — режем по строкам
        while len(paragraph) > MAX_MESSAGE_LENGTH:
            cut = paragraph.rfind("\n", 0, MAX_MESSAGE_LENGTH)
            if cut <= 0:
                cut = MAX_MESSAGE_LENGTH
            parts.append(paragraph[:cut])
            paragraph = paragraph[cut:].lstrip()
        current = paragraph

    if current:
        parts.append(current)
    return parts


async def _attachment_for_figures(
    db: AsyncSession, vk_api: VkApi, peer_id: int, figures: list
) -> str | None:
    """Готовит вложение с иллюстрациями из учебника.

    Сама вырезка строится из исходного PDF по координатам рисунка, а
    идентификатор загруженного вложения сохраняется: повторно грузить
    один и тот же рисунок на серверы VK ни к чему.
    """
    attachments: list[str] = []

    for retrieved in figures:
        figure = await db.get(DocumentFigure, retrieved.figure_id)
        if figure is None:
            continue

        if figure.vk_attachment_id:
            attachments.append(figure.vk_attachment_id)
            continue

        path = await figure_service.preview_for(db, figure)
        if path is None or not Path(path).exists():
            # Ссылка на файл и страницу в тексте ответа есть и без картинки
            continue

        attachment_id = await vk_api.upload_photo(peer_id, Path(path))
        if attachment_id:
            figure.vk_attachment_id = attachment_id
            await db.commit()
            attachments.append(attachment_id)

    return ",".join(attachments) if attachments else None


def _menu_state_key(peer_id: int) -> str:
    return f"vk:menu:{peer_id}"


def _button_rows(labels: list[str], columns: int = 2) -> list[list[str]]:
    return [labels[index : index + columns] for index in range(0, len(labels), columns)]


async def _show_schedule_page(
    db: AsyncSession,
    redis: aioredis.Redis,
    vk_api: VkApi,
    peer_id: int,
    page: int,
) -> None:
    schedules = list(
        (
            await db.execute(
                select(GroupSchedule)
                .where(GroupSchedule.is_active.is_(True))
                .order_by(GroupSchedule.group_name)
            )
        ).scalars().all()
    )
    if not schedules:
        await redis.set(_menu_state_key(peer_id), "organization", ex=MENU_STATE_TTL_SECONDS)
        await vk_api.send_message(
            peer_id, "Расписания пока не добавлены.", keyboard=dumps_keyboard(MENU_ORGANIZATION)
        )
        return

    page_count = (len(schedules) + SCHEDULE_PAGE_SIZE - 1) // SCHEDULE_PAGE_SIZE
    page = max(0, min(page, page_count - 1))
    start = page * SCHEDULE_PAGE_SIZE
    labels = [schedule.group_name for schedule in schedules[start : start + SCHEDULE_PAGE_SIZE]]
    rows = _button_rows(labels)
    navigation = []
    if page > 0:
        navigation.append("Предыдущие группы")
    if page + 1 < page_count:
        navigation.append("Следующие группы")
    rows.extend(_button_rows(navigation))
    rows.append(["Назад"])

    await redis.set(
        _menu_state_key(peer_id), f"schedules:{page}", ex=MENU_STATE_TTL_SECONDS
    )
    await vk_api.send_message(
        peer_id,
        f"Выберите группу ({page + 1}/{page_count}):",
        keyboard=dumps_keyboard(rows),
    )


async def _show_teachers(
    db: AsyncSession, vk_api: VkApi, peer_id: int
) -> None:
    teachers = list(
        (
            await db.execute(
                select(Teacher)
                .where(Teacher.is_active.is_(True))
                .order_by(Teacher.full_name, Teacher.id)
            )
        ).scalars().all()
    )
    if not teachers:
        text = "Список преподавателей пока не заполнен."
    else:
        text = "Преподаватели кафедры:\n\n" + "\n\n".join(
            f"{teacher.full_name}\n{teacher.position}\nОбласть: {teacher.area}"
            for teacher in teachers
        )

    parts = split_message(text)
    for index, part in enumerate(parts):
        await vk_api.send_message(
            peer_id,
            part,
            keyboard=dumps_keyboard(MENU_ORGANIZATION) if index == len(parts) - 1 else None,
        )


async def _send_schedule(
    db: AsyncSession, vk_api: VkApi, peer_id: int, group_name: str
) -> bool:
    schedule = (
        await db.execute(
            select(GroupSchedule).where(
                GroupSchedule.is_active.is_(True),
                func.lower(GroupSchedule.group_name) == group_name.lower(),
            )
        )
    ).scalar_one_or_none()
    if schedule is None:
        return False

    attachment = schedule.vk_attachment_id
    path = Path(schedule.stored_path)
    if not attachment and path.exists():
        if schedule.mime_type == "application/pdf":
            attachment = await vk_api.upload_document(peer_id, path)
        else:
            attachment = await vk_api.upload_photo(peer_id, path)
        if attachment:
            schedule.vk_attachment_id = attachment
            await db.commit()

    text = f"Расписание группы {schedule.group_name}."
    if not attachment:
        text += " Не удалось прикрепить изображение, обратитесь к администратору."
    await vk_api.send_message(
        peer_id,
        text,
        attachment=attachment,
        keyboard=dumps_keyboard(MENU_ORGANIZATION),
    )
    return True


async def _handle_menu(
    db: AsyncSession,
    redis: aioredis.Redis,
    vk_api: VkApi,
    peer_id: int,
    text: str,
) -> bool:
    state_key = _menu_state_key(peer_id)
    state = await redis.get(state_key) or "chat"

    if text.lower() in {"/start", "начать", "меню", "главное меню"}:
        await redis.set(state_key, "main", ex=MENU_STATE_TTL_SECONDS)
        await vk_api.send_message(
            peer_id, "Выберите раздел:", keyboard=dumps_keyboard(MENU_MAIN)
        )
        return True

    if text.casefold() == "чат":
        await redis.set(state_key, "chat", ex=MENU_STATE_TTL_SECONDS)
        await vk_api.send_message(
            peer_id, "Режим чата по базе знаний. Напишите вопрос.",
            keyboard=dumps_keyboard(MENU_MAIN),
        )
        return True

    if text.casefold() == "орг. информация":
        await redis.set(state_key, "organization", ex=MENU_STATE_TTL_SECONDS)
        await vk_api.send_message(
            peer_id, "Выберите раздел:", keyboard=dumps_keyboard(MENU_ORGANIZATION)
        )
        return True

    if text.casefold() == "главное меню":
        await redis.set(state_key, "main", ex=MENU_STATE_TTL_SECONDS)
        await vk_api.send_message(
            peer_id, "Выберите раздел:", keyboard=dumps_keyboard(MENU_MAIN)
        )
        return True

    if text.casefold() == "назад":
        if state.startswith("schedules:"):
            await redis.set(state_key, "organization", ex=MENU_STATE_TTL_SECONDS)
            await vk_api.send_message(
                peer_id, "Выберите раздел:", keyboard=dumps_keyboard(MENU_ORGANIZATION)
            )
            return True
        if state == "organization":
            await redis.set(state_key, "main", ex=MENU_STATE_TTL_SECONDS)
            await vk_api.send_message(
                peer_id, "Выберите раздел:", keyboard=dumps_keyboard(MENU_MAIN)
            )
            return True

    if text.casefold() == "расписание":
        await _show_schedule_page(db, redis, vk_api, peer_id, 0)
        return True

    if state.startswith("schedules:") and text.casefold() in {
        "предыдущие группы", "следующие группы"
    }:
        page = int(state.partition(":")[2])
        await _show_schedule_page(
            db, redis, vk_api, peer_id, page + (1 if text.casefold() == "следующие группы" else -1)
        )
        return True

    if text.casefold() == "преподаватели":
        await redis.set(state_key, "organization", ex=MENU_STATE_TTL_SECONDS)
        await _show_teachers(db, vk_api, peer_id)
        return True

    if state.startswith("schedules:") and await _send_schedule(db, vk_api, peer_id, text):
        await redis.set(state_key, "organization", ex=MENU_STATE_TTL_SECONDS)
        return True

    return False


async def handle_message(
    db: AsyncSession,
    redis: aioredis.Redis,
    vk_api: VkApi,
    peer_id: int,
    from_id: int,
    text: str,
) -> None:
    text = (text or "").strip()
    if not text:
        return

    user = await get_or_create_user(db, vk_api, from_id)

    if user.is_blocked:
        log.info("vk_blocked_user_ignored", vk_id=from_id)
        return

    if await _handle_menu(db, redis, vk_api, peer_id, text):
        return

    limit = int(await settings_service.get(db, "rate_limit_per_minute"))
    if not await check_rate_limit(redis, from_id, limit):
        await chat_service.log_rate_limited(
            db, Channel.vk, str(peer_id), text, RATE_LIMITED
        )
        await vk_api.send_message(
            peer_id, RATE_LIMITED, keyboard=dumps_keyboard(MENU_MAIN)
        )
        return

    typing_task = asyncio.create_task(_keep_typing(vk_api, peer_id))
    try:
        result, _ = await chat_service.ask(
            db,
            text,
            channel=Channel.vk,
            external_id=str(peer_id),
            vk_user=user,
        )
    finally:
        typing_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await typing_task

    attachment = None
    if result.figures and not result.refused:
        attachment = await _attachment_for_figures(db, vk_api, peer_id, result.figures)

    chunks = split_message(result.answer)
    for i, chunk in enumerate(chunks):
        # Вложение отправляем один раз, с последней частью ответа
        await vk_api.send_message(
            peer_id,
            chunk,
            attachment=attachment if i == len(chunks) - 1 else None,
            keyboard=dumps_keyboard(MENU_MAIN) if i == len(chunks) - 1 else None,
        )

    log.info(
        "vk_answered",
        vk_id=from_id,
        refused=result.refused,
        total_ms=result.total_ms,
        parts=len(chunks),
    )


def parse_event(event: dict) -> tuple[int, int, str] | None:
    """Достаёт (peer_id, from_id, текст) из события message_new."""
    if event.get("type") != "message_new":
        return None

    obj = event.get("object", {})
    message = obj.get("message", obj)

    peer_id = message.get("peer_id")
    from_id = message.get("from_id")
    text = message.get("text", "")

    if peer_id is None or from_id is None:
        return None
    # Сообщения от сообществ игнорируем
    if from_id < 0:
        return None

    return int(peer_id), int(from_id), str(text)


def dumps_keyboard(rows: list[list[str]]) -> str:
    """Создаёт постоянную клавиатуру разделов VK."""
    return json.dumps(
        {
            "one_time": False,
            "inline": False,
            "buttons": [
                [
                    {"action": {"type": "text", "label": label}, "color": "secondary"}
                    for label in row
                ]
                for row in rows
            ],
        },
        ensure_ascii=False,
    )
