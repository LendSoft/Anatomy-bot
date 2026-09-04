"""Контрольные наборы вопросов и прогоны тестирования.

По ТЗ (раздел 9) преподаватели готовят набор контрольных вопросов, и
перед внедрением нужно проверить, что бот отвечает в соответствии с
учебной литературой. Отсюда: наборы вопросов с эталонными ответами,
прогоны и оценки — автоматическая (LLM-судья) плюс ручная.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class RunStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class TestSet(Base, TimestampMixin):
    """Набор контрольных вопросов, например «Черепные нервы»."""

    __tablename__ = "test_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    section: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    questions: Mapped[list[TestQuestion]] = relationship(
        back_populates="test_set", cascade="all, delete-orphan", passive_deletes=True
    )


class TestQuestion(Base, TimestampMixin):
    __tablename__ = "test_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    test_set_id: Mapped[int] = mapped_column(
        ForeignKey("test_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    # Эталонный ответ от преподавателя — с ним сравнивает судья
    reference_answer: Mapped[str | None] = mapped_column(Text)
    expected_source: Mapped[str | None] = mapped_column(String(512))
    # Вопросы, на которые бот ДОЛЖЕН ответить отказом (нет в базе, вне предмета)
    should_refuse: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tags: Mapped[list | None] = mapped_column(JSONB)

    test_set: Mapped[TestSet] = relationship(back_populates="questions")


class TestRun(Base, TimestampMixin):
    """Один прогон набора на конкретных настройках."""

    __tablename__ = "test_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    test_set_id: Mapped[int] = mapped_column(
        ForeignKey("test_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, name="run_status"), default=RunStatus.pending, nullable=False, index=True
    )

    # Слепок настроек и промпта на момент прогона — иначе через неделю
    # непонятно, почему цифры отличаются
    settings_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    prompt_version: Mapped[int | None] = mapped_column(Integer)
    llm_model: Mapped[str | None] = mapped_column(String(255))

    total_questions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_questions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    avg_score: Mapped[float | None] = mapped_column(Float)
    refusal_rate: Mapped[float | None] = mapped_column(Float)
    avg_latency_ms: Mapped[float | None] = mapped_column(Float)

    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    results: Mapped[list[TestResult]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )


class TestResult(Base):
    __tablename__ = "test_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("test_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[int] = mapped_column(
        ForeignKey("test_questions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    answer: Mapped[str | None] = mapped_column(Text)
    refused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    retrieved_chunks: Mapped[list | None] = mapped_column(JSONB)
    top_score: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    # Оценка LLM-судьи 1..5 и обоснование
    judge_score: Mapped[float | None] = mapped_column(Float)
    judge_comment: Mapped[str | None] = mapped_column(Text)
    # Ручная оценка преподавателя перекрывает автоматическую
    manual_score: Mapped[float | None] = mapped_column(Float)
    manual_comment: Mapped[str | None] = mapped_column(Text)

    error_message: Mapped[str | None] = mapped_column(Text)

    run: Mapped[TestRun] = relationship(back_populates="results")

    __table_args__ = (Index("ix_test_results_run_question", "run_id", "question_id", unique=True),)
