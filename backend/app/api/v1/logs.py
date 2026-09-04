"""Журнал диалогов.

Ключевой инструмент отладки: по каждому ответу видно, какие фрагменты
нашлись, с какими оценками и на каких параметрах он был получен.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.api.deps import CurrentAdmin, DbSession
from app.models.chat import AnswerStatus, Channel, Conversation, Message
from app.schemas.chat import ConversationOut, MessageOut
from app.schemas.common import Page

router = APIRouter(prefix="/logs", tags=["Логи"])


@router.get("/conversations", response_model=Page[ConversationOut])
async def list_conversations(
    db: DbSession,
    _: CurrentAdmin,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    channel: Channel | None = None,
) -> Page[ConversationOut]:
    query = select(Conversation)
    count_query = select(func.count(Conversation.id))

    if channel:
        query = query.where(Conversation.channel == channel)
        count_query = count_query.where(Conversation.channel == channel)

    total = (await db.execute(count_query)).scalar_one()

    rows = (
        await db.execute(
            query.order_by(Conversation.last_message_at.desc().nulls_last())
            .offset((page - 1) * size)
            .limit(size)
        )
    ).scalars().all()

    # Счётчик сообщений одним запросом на страницу, а не по одному на диалог
    counts: dict[int, int] = {}
    if rows:
        count_rows = (
            await db.execute(
                select(Message.conversation_id, func.count(Message.id))
                .where(Message.conversation_id.in_([r.id for r in rows]))
                .group_by(Message.conversation_id)
            )
        ).all()
        counts = dict(count_rows)

    items = []
    for row in rows:
        item = ConversationOut.model_validate(row)
        item.messages_count = counts.get(row.id, 0)
        items.append(item)

    return Page[ConversationOut](items=items, total=total, page=page, size=size)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def get_conversation_messages(
    conversation_id: int, db: DbSession, _: CurrentAdmin
) -> list[Message]:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Диалог не найден")

    return list(
        (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at)
            )
        ).scalars().all()
    )


@router.get("/messages", response_model=Page[MessageOut])
async def list_messages(
    db: DbSession,
    _: CurrentAdmin,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    status_filter: AnswerStatus | None = Query(None, alias="status"),
    channel: Channel | None = None,
    search: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    min_latency_ms: int | None = None,
) -> Page[MessageOut]:
    query = select(Message)
    count_query = select(func.count(Message.id))

    conditions = []
    if status_filter:
        conditions.append(Message.status == status_filter)
    if search:
        conditions.append(Message.content.ilike(f"%{search}%"))
    if date_from:
        conditions.append(Message.created_at >= date_from)
    if date_to:
        conditions.append(Message.created_at <= date_to)
    if min_latency_ms:
        conditions.append(Message.total_ms >= min_latency_ms)

    if channel:
        subquery = select(Conversation.id).where(Conversation.channel == channel)
        conditions.append(Message.conversation_id.in_(subquery))

    for condition in conditions:
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = (await db.execute(count_query)).scalar_one()
    rows = (
        await db.execute(
            query.order_by(Message.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    ).scalars().all()

    return Page[MessageOut](
        items=[MessageOut.model_validate(row) for row in rows],
        total=total,
        page=page,
        size=size,
    )


@router.get("/messages/{message_id}", response_model=MessageOut)
async def get_message(message_id: int, db: DbSession, _: CurrentAdmin) -> Message:
    message = await db.get(Message, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    return message
