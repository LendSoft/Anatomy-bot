"""Диалоги и журнал запросов.

Для каждого ответа сохраняем не только текст, но и что именно было найдено
в базе (с оценками) и какой промпт использовался. Без этого отлаживать
RAG невозможно: непонятно, ошибся поиск или модель.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
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


class Channel(str, enum.Enum):
    vk = "vk"
    web = "web"          # веб-виджет / проверка из админки
    test = "test"        # прогон тестового набора


class MessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"


class AnswerStatus(str, enum.Enum):
    answered = "answered"        # ответ сформирован по найденным материалам
    refused = "refused"          # в базе не нашлось — честно сказали об этом
    error = "error"              # сбой LLM или поиска
    rate_limited = "rate_limited"


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel: Mapped[Channel] = mapped_column(
        Enum(Channel, name="chat_channel"), nullable=False, index=True
    )
    # Для VK — peer_id, для веба — id сессии
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    vk_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("vk_users.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str | None] = mapped_column(String(512))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (Index("ix_conversations_channel_ext", "channel", "external_id"),)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, name="message_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # --- только для ответов ассистента ---
    status: Mapped[AnswerStatus | None] = mapped_column(Enum(AnswerStatus, name="answer_status"))
    # Найденные фрагменты: [{"chunk_id", "document_id", "title", "page", "score", "content"}]
    retrieved_chunks: Mapped[list | None] = mapped_column(JSONB)
    # Иллюстрации, на которые сослался ответ:
    # [{"figure_id", "document_title", "page_number", "label", "score"}]
    attached_figures: Mapped[list | None] = mapped_column(JSONB)
    # Слепок параметров генерации, чтобы понять, на каких настройках получен ответ
    generation_params: Mapped[dict | None] = mapped_column(JSONB)
    prompt_version: Mapped[int | None] = mapped_column(Integer)

    llm_provider: Mapped[str | None] = mapped_column(String(64))
    llm_model: Mapped[str | None] = mapped_column(String(255))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)

    retrieval_ms: Mapped[int | None] = mapped_column(Integer)
    generation_ms: Mapped[int | None] = mapped_column(Integer)
    total_ms: Mapped[int | None] = mapped_column(Integer)
    top_score: Mapped[float | None] = mapped_column(Float)

    error_message: Mapped[str | None] = mapped_column(Text)
    # Оценка студента: 1 (полезно) / -1 (бесполезно)
    feedback: Mapped[int | None] = mapped_column(Integer)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    __table_args__ = (
        Index("ix_messages_conv_created", "conversation_id", "created_at"),
        Index("ix_messages_status_created", "status", "created_at"),
    )
