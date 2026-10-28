"""Проверка бота из админ-панели.

Результат здесь показывает
реальное поведение бота, а не отдельную ветку кода.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentAdmin, DbSession
from app.models.chat import Channel, Message
from app.schemas.chat import (
    AskRequest,
    AskResponse,
    FeedbackRequest,
    FigureRefOut,
    SourceOut,
)
from app.schemas.common import MessageResponse
from app.services import chat_service

router = APIRouter(prefix="/chat", tags=["Проверка бота"])


@router.post("/ask", response_model=AskResponse)
async def ask(payload: AskRequest, db: DbSession, admin: CurrentAdmin) -> AskResponse:
    session_id = payload.session_id or f"admin-{admin.id}-{uuid.uuid4().hex[:8]}"

    result, message = await chat_service.ask(
        db,
        payload.question,
        channel=Channel.web,
        external_id=session_id,
        section=payload.section,
        overrides=payload.overrides,
    )

    return AskResponse(
        answer=result.answer,
        refused=result.refused,
        message_id=message.id,
        sources=[
            SourceOut(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                document_title=chunk.document_title,
                heading=chunk.heading,
                page_from=chunk.page_from,
                page_to=chunk.page_to,
                score=round(chunk.score, 4),
                content=chunk.content,
            )
            for chunk in result.chunks
        ],
        figures=[
            FigureRefOut(
                figure_id=figure.figure_id,
                document_id=figure.document_id,
                document_title=figure.document_title,
                page_number=figure.page_number,
                kind=figure.kind,
                caption=figure.caption(),
                labels=figure.labels,
                source=figure.source,
                score=round(figure.score, 4),
                preview_url=f"/api/v1/figures/{figure.figure_id}/preview",
            )
            for figure in result.figures
        ],
        top_score=result.top_score,
        llm_model=result.llm_model,
        llm_provider=result.llm_provider,
        retrieval_ms=result.retrieval_ms,
        generation_ms=result.generation_ms,
        total_ms=result.total_ms,
        error=result.error,
    )


@router.post("/messages/{message_id}/feedback", response_model=MessageResponse)
async def set_feedback(
    message_id: int, payload: FeedbackRequest, db: DbSession, _: CurrentAdmin
) -> MessageResponse:
    message = await db.get(Message, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")

    message.feedback = payload.value
    await db.commit()
    return MessageResponse(detail="Оценка сохранена")
