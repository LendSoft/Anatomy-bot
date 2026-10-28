"""Схемы чата, логов и тестирования."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.chat import AnswerStatus, Channel, MessageRole
from app.models.evaluation import RunStatus


class AskRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=2000)
    session_id: str | None = Field(None, max_length=128)
    section: str | None = Field(None, max_length=255)
    # Разовые параметры для проверки, без сохранения в настройки
    overrides: dict[str, Any] | None = None


class SourceOut(BaseModel):
    chunk_id: int
    document_id: int
    document_title: str
    heading: str | None
    page_from: int | None
    page_to: int | None
    score: float
    content: str


class FigureRefOut(BaseModel):
    """Иллюстрация, на которую бот сослался в ответе."""

    figure_id: int
    document_id: int
    document_title: str
    page_number: int
    kind: str
    caption: str
    # Названия структур, подписанных на изображении
    labels: list[str]
    # Нашлась на странице ответа или отдельным поиском
    source: str
    score: float
    preview_url: str


class AskResponse(BaseModel):
    answer: str
    refused: bool
    message_id: int
    sources: list[SourceOut]
    figures: list[FigureRefOut]
    top_score: float | None
    llm_model: str | None
    llm_provider: str | None
    retrieval_ms: int
    generation_ms: int
    total_ms: int
    error: str | None = None


class FeedbackRequest(BaseModel):
    # 1 — ответ помог, -1 — не помог
    value: int = Field(..., ge=-1, le=1)


# ------------------------------------------------------------------- логи


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: MessageRole
    content: str
    created_at: datetime
    status: AnswerStatus | None
    retrieved_chunks: list | None
    attached_figures: list | None
    generation_params: dict | None
    prompt_version: int | None
    llm_provider: str | None
    llm_model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    retrieval_ms: int | None
    generation_ms: int | None
    total_ms: int | None
    top_score: float | None
    error_message: str | None
    feedback: int | None


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel: Channel
    external_id: str
    title: str | None
    last_message_at: datetime | None
    created_at: datetime
    messages_count: int = 0


# --------------------------------------------------------------- тесты


class TestQuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    test_set_id: int
    question: str
    reference_answer: str | None
    expected_source: str | None
    should_refuse: bool
    tags: list | None


class TestQuestionCreate(BaseModel):
    question: str = Field(..., min_length=3)
    reference_answer: str | None = None
    expected_source: str | None = Field(None, max_length=512)
    should_refuse: bool = False
    tags: list[str] | None = None


class TestSetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    section: str | None
    is_active: bool
    created_at: datetime
    questions_count: int = 0


class TestSetCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: str | None = None
    section: str | None = Field(None, max_length=255)


class TestRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    test_set_id: int
    name: str | None
    status: RunStatus
    settings_snapshot: dict | None
    prompt_version: int | None
    llm_model: str | None
    total_questions: int
    completed_questions: int
    avg_score: float | None
    refusal_rate: float | None
    avg_latency_ms: float | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class TestRunCreate(BaseModel):
    test_set_id: int
    name: str | None = Field(None, max_length=255)
    overrides: dict[str, Any] | None = None


class TestResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    question_id: int
    answer: str | None
    refused: bool
    retrieved_chunks: list | None
    top_score: float | None
    latency_ms: int | None
    judge_score: float | None
    judge_comment: str | None
    manual_score: float | None
    manual_comment: str | None
    error_message: str | None
    question: str | None = None
    reference_answer: str | None = None


class ManualScoreRequest(BaseModel):
    manual_score: float = Field(..., ge=1, le=5)
    manual_comment: str | None = None
