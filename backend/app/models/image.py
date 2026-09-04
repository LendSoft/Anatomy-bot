"""Изображения из анатомических атласов.

По ТЗ бот должен уметь приложить к ответу подходящую иллюстрацию.
Поиск идёт по вектору описания и по тегам структур — сама картинка
пока не эмбеддится, но модель поля это допускает (задел под
мультимодальность).
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.db.base import Base, TimestampMixin


class AtlasImage(Base, TimestampMixin):
    __tablename__ = "atlas_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # Анатомические структуры на изображении — по-русски и на латыни.
    # Именно по ним чаще всего идёт подбор картинки к ответу.
    structures_ru: Mapped[list[str] | None] = mapped_column(ARRAY(String(255)))
    structures_lat: Mapped[list[str] | None] = mapped_column(ARRAY(String(255)))
    section: Mapped[str | None] = mapped_column(String(255), index=True)

    # Источник — обязателен, в том числе из-за авторских прав на атласы
    source_title: Mapped[str | None] = mapped_column(String(512))
    source_authors: Mapped[str | None] = mapped_column(String(512))
    source_page: Mapped[int | None] = mapped_column(Integer)
    license_note: Mapped[str | None] = mapped_column(String(512))

    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    thumbnail_path: Mapped[str | None] = mapped_column(String(1024))
    mime_type: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)

    # ID вложения в VK (photo-XXX_YYY): загруженную однажды картинку
    # переиспользуем, чтобы не грузить её на серверы VK при каждом ответе
    vk_attachment_id: Mapped[str | None] = mapped_column(String(128))

    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embedding_dim))
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    extra: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_atlas_images_search", "search_vector", postgresql_using="gin"),
        Index(
            "ix_atlas_images_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
