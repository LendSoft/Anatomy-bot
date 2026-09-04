"""Учебные материалы и их чанки в векторной базе."""

from __future__ import annotations

import enum
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.db.base import Base, TimestampMixin


class DocumentStatus(str, enum.Enum):
    pending = "pending"          # загружен, ждёт обработки
    parsing = "parsing"          # извлекается текст
    chunking = "chunking"        # режется на фрагменты
    embedding = "embedding"      # считаются векторы
    ready = "ready"              # доступен для поиска
    failed = "failed"


class Document(Base, TimestampMixin):
    """Учебник, атлас или методичка.

    Метаданные источника (автор, издание) обязательны: по ТЗ бот должен
    указывать, откуда взят ответ.
    """

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    authors: Mapped[str | None] = mapped_column(String(512))
    edition: Mapped[str | None] = mapped_column(String(255))
    year: Mapped[int | None] = mapped_column(Integer)
    # Раздел курса по структуре кафедры: остеология, миология, ангиология...
    section: Mapped[str | None] = mapped_column(String(255), index=True)

    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    # sha256 — не даём загрузить один и тот же учебник дважды
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)

    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status"),
        default=DocumentStatus.pending,
        nullable=False,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    pages_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunks_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Включён ли документ в поиск — можно временно отключить, не удаляя
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extra: Mapped[dict | None] = mapped_column(JSONB)

    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class DocumentChunk(Base):
    """Фрагмент документа с вектором и полнотекстовым индексом.

    Гибридный поиск: косинусное расстояние по `embedding` + BM25-подобный
    ранг по `search_vector` (русская конфигурация Postgres). Один только
    вектор плохо ловит точные латинские термины, один только полнотекст —
    переформулировки вопроса.
    """

    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Заголовок раздела, из которого взят фрагмент — идёт в цитату
    heading: Mapped[str | None] = mapped_column(String(512))
    page_from: Mapped[int | None] = mapped_column(Integer)
    page_to: Mapped[int | None] = mapped_column(Integer)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embedding_dim))
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR)

    extra: Mapped[dict | None] = mapped_column(JSONB)

    document: Mapped[Document] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("ix_document_chunks_doc_idx", "document_id", "chunk_index", unique=True),
        Index("ix_document_chunks_search", "search_vector", postgresql_using="gin"),
        # HNSW заметно быстрее IVFFlat на выборках такого размера и не требует
        # переобучения индекса при доливке новых документов
        Index(
            "ix_document_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
