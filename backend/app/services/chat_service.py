"""Ведение диалога и журналирование ответов."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.chat import AnswerStatus, Channel, Conversation, Message, MessageRole
from app.models.user import VkUser
from app.rag import pipeline
from app.rag.pipeline import AnswerResult
from app.services import settings_service

log = get_logger(__name__)


async def get_or_create_conversation(
    db: AsyncSession, channel: Channel, external_id: str, vk_user_id: int | None = None
) -> Conversation:
    conversation = (
        await db.execute(
            select(Conversation).where(
                Conversation.channel == channel,
                Conversation.external_id == external_id,
            )
        )
    ).scalar_one_or_none()

    if conversation is None:
        conversation = Conversation(
            channel=channel, external_id=external_id, vk_user_id=vk_user_id
        )
        db.add(conversation)
        await db.flush()

    return conversation


async def get_history(
    db: AsyncSession, conversation_id: int, turns: int
) -> list[tuple[str, str]]:
    """Последние пары «вопрос — ответ» для передачи в модель.

    Отказы в историю не берём: они не несут содержания и только съедают
    контекст.
    """
    if turns <= 0:
        return []

    rows = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(desc(Message.created_at))
            .limit(turns * 4)
        )
    ).scalars().all()

    rows = list(reversed(rows))
    history: list[tuple[str, str]] = []
    pending_question: str | None = None

    for message in rows:
        if message.role == MessageRole.user:
            pending_question = message.content
        elif pending_question is not None:
            if message.status == AnswerStatus.answered:
                history.append((pending_question, message.content))
            pending_question = None

    return history[-turns:]


async def ask(
    db: AsyncSession,
    question: str,
    *,
    channel: Channel,
    external_id: str,
    vk_user: VkUser | None = None,
    section: str | None = None,
    overrides: dict | None = None,
    include_sources: bool = True,
) -> tuple[AnswerResult, Message]:
    """Полный цикл: сохранить вопрос, получить ответ, записать его в журнал."""
    conversation = await get_or_create_conversation(
        db, channel, external_id, vk_user.id if vk_user else None
    )

    now = datetime.now(UTC)
    db.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.user,
            content=question,
            created_at=now,
        )
    )
    await db.flush()

    turns = int(await settings_service.get(db, "history_turns"))
    history = await get_history(db, conversation.id, turns)

    result = await pipeline.answer_question(
        db,
        question,
        history=history,
        section=section,
        overrides=overrides,
        include_sources=include_sources,
    )

    if result.error and not result.refused:
        status = AnswerStatus.error
    elif result.refused:
        status = AnswerStatus.refused
    else:
        status = AnswerStatus.answered

    answer_message = Message(
        conversation_id=conversation.id,
        role=MessageRole.assistant,
        content=result.answer,
        created_at=datetime.now(UTC),
        status=status,
        retrieved_chunks=[c.to_log_dict() for c in result.chunks],
        attached_figures=[f.to_log_dict() for f in result.figures] or None,
        generation_params=result.generation_params or None,
        prompt_version=result.prompt_version,
        llm_provider=result.llm_provider,
        llm_model=result.llm_model,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        retrieval_ms=result.retrieval_ms,
        generation_ms=result.generation_ms,
        total_ms=result.total_ms,
        top_score=result.top_score,
        error_message=result.error,
    )
    db.add(answer_message)

    conversation.last_message_at = answer_message.created_at
    if conversation.title is None:
        conversation.title = question[:200]

    if vk_user is not None:
        vk_user.messages_count += 1
        vk_user.last_seen_at = answer_message.created_at

    await db.commit()
    await db.refresh(answer_message)

    return result, answer_message


async def log_rate_limited(
    db: AsyncSession, channel: Channel, external_id: str, question: str, message: str
) -> None:
    """Отдельная запись, чтобы отказы по лимиту были видны в статистике."""
    conversation = await get_or_create_conversation(db, channel, external_id)
    now = datetime.now(UTC)

    db.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.user,
            content=question,
            created_at=now,
        )
    )
    db.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.assistant,
            content=message,
            created_at=now,
            status=AnswerStatus.rate_limited,
        )
    )
    await db.commit()
