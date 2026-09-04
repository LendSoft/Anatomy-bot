"""Промпты с версионированием.

Промпт — то, что правят чаще всего, и неудачная правка сразу видна на
качестве ответов. Поэтому храним версии: каждая правка создаёт новую
запись, активна всегда ровно одна, откат — один клик в админке.
"""

from __future__ import annotations

import enum

from sqlalchemy import Boolean, Enum, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class PromptKind(str, enum.Enum):
    system = "system"              # основной системный промпт бота
    reference_answers = "reference_answers"  # эталонные ответы (few-shot)
    query_rewrite = "query_rewrite"          # переформулировка вопроса перед поиском
    judge = "judge"                          # промпт LLM-судьи для автотестов


class Prompt(Base, TimestampMixin):
    __tablename__ = "prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[PromptKind] = mapped_column(
        Enum(PromptKind, name="prompt_kind"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    name: Mapped[str | None] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Для kind=reference_answers: [{"question": "...", "answer": "..."}]
    examples: Mapped[list | None] = mapped_column(JSONB)

    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255))
    comment: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_prompts_kind_version", "kind", "version", unique=True),
        # Частичный уникальный индекс: активная версия каждого вида ровно одна
        Index(
            "ix_prompts_kind_active",
            "kind",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )
