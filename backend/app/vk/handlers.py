"""Обработка сообщений от студентов во ВКонтакте."""

from __future__ import annotations

import json
from pathlib import Path

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.chat import Channel
from app.models.image import AtlasImage
from app.models.user import VkUser
from app.services import chat_service, settings_service
from app.vk.api import VkApi

log = get_logger(__name__)

# Ограничение VK на длину сообщения — режем с запасом
MAX_MESSAGE_LENGTH = 4000

WELCOME = (
    "Здравствуйте! Я помогу разобраться в анатомии человека.\n\n"
    "Задайте вопрос своими словами, например:\n"
    "• Какие ветви имеет наружная сонная артерия?\n"
    "• Расскажи строение плечевой кости\n"
    "• Что проходит через яремное отверстие?\n\n"
    "Отвечаю только по учебным материалам кафедры и всегда указываю источник. "
    "Если нужных сведений в базе нет, я скажу об этом прямо, а не буду "
    "додумывать.\n\n"
    "Команды: /помощь — эта справка."
)

RATE_LIMITED = (
    "Слишком много запросов подряд. Подождите минуту, пожалуйста — "
    "я обрабатываю вопросы по очереди."
)

COMMANDS_HELP = {"/помощь", "/help", "помощь", "начать", "start", "/start"}


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


async def _attachment_for_images(
    db: AsyncSession, vk_api: VkApi, peer_id: int, images: list[dict]
) -> str | None:
    """Готовит вложение с иллюстрациями.

    Идентификатор загруженной картинки сохраняем: повторно грузить один
    и тот же рисунок из атласа на серверы VK ни к чему.
    """
    attachments: list[str] = []

    for image_info in images:
        image = await db.get(AtlasImage, image_info["image_id"])
        if image is None:
            continue

        if image.vk_attachment_id:
            attachments.append(image.vk_attachment_id)
            continue

        path = Path(image.stored_path)
        if not path.exists():
            continue

        attachment_id = await vk_api.upload_photo(peer_id, path)
        if attachment_id:
            image.vk_attachment_id = attachment_id
            await db.commit()
            attachments.append(attachment_id)

    return ",".join(attachments) if attachments else None


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

    if text.lower() in COMMANDS_HELP:
        await vk_api.send_message(peer_id, WELCOME)
        return

    user = await get_or_create_user(db, vk_api, from_id)

    if user.is_blocked:
        log.info("vk_blocked_user_ignored", vk_id=from_id)
        return

    limit = int(await settings_service.get(db, "rate_limit_per_minute"))
    if not await check_rate_limit(redis, from_id, limit):
        await chat_service.log_rate_limited(
            db, Channel.vk, str(peer_id), text, RATE_LIMITED
        )
        await vk_api.send_message(peer_id, RATE_LIMITED)
        return

    await vk_api.set_typing(peer_id)

    result, _ = await chat_service.ask(
        db,
        text,
        channel=Channel.vk,
        external_id=str(peer_id),
        vk_user=user,
    )

    attachment = None
    if result.images and not result.refused:
        attachment = await _attachment_for_images(db, vk_api, peer_id, result.images)

    chunks = split_message(result.answer)
    for i, chunk in enumerate(chunks):
        # Вложение отправляем один раз, с последней частью ответа
        await vk_api.send_message(
            peer_id, chunk, attachment=attachment if i == len(chunks) - 1 else None
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


def dumps_keyboard(buttons: list[str]) -> str:
    """Клавиатура с подсказками тем — на будущее, для обучающего режима."""
    return json.dumps(
        {
            "one_time": False,
            "inline": True,
            "buttons": [
                [{"action": {"type": "text", "label": label}, "color": "secondary"}]
                for label in buttons
            ],
        },
        ensure_ascii=False,
    )
