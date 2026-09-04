"""Словарь анатомических терминов ru ↔ lat.

Нужен для расширения запроса: студент пишет «наружная сонная артерия»,
а в учебнике фрагмент подписан «arteria carotis externa» (или наоборот).
Векторный поиск это ловит не всегда, особенно на редких терминах,
поэтому перед поиском подмешиваем синонимы из словаря.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AnatomyTerm(Base, TimestampMixin):
    __tablename__ = "anatomy_terms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    term_ru: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    term_lat: Mapped[str | None] = mapped_column(String(255), index=True)
    # Сокращения, устаревшие названия, разговорные варианты
    synonyms: Mapped[list[str] | None] = mapped_column(ARRAY(String(255)))
    section: Mapped[str | None] = mapped_column(String(255), index=True)
    definition: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        Index("ix_anatomy_terms_ru_lat", "term_ru", "term_lat", unique=True),
        # Нечёткий поиск по началу термина для автодополнения в админке
        Index("ix_anatomy_terms_ru_trgm", "term_ru",
              postgresql_using="gin", postgresql_ops={"term_ru": "gin_trgm_ops"}),
    )
