"""Иллюстрации, найденные внутри учебных материалов.

Картинки не загружаются отдельно и не описываются вручную: они
извлекаются из того же PDF или DOCX, что уже лежит в базе знаний. От
каждой иллюстрации нужны источник (документ и страница), подпись из
книги и текст выносок — по нему рисунок и находится, а бот может
пересказать, что на нём обозначено.

Файл с картинкой здесь не хранится: лежат координаты на странице, а
изображение вырезается из исходного документа по запросу.
"""

from __future__ import annotations

import enum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.db.base import Base, TimestampMixin


class FigureKind(str, enum.Enum):
    figure = "figure"   # рисунок внутри текста, с подписью «Рис. 5.3»
    plate = "plate"     # страница-иллюстрация атласа с выносками
    table = "table"     # подпись «Таблица N»
    page = "page"       # отсканированная страница целиком


class DocumentFigure(Base, TimestampMixin):
    __tablename__ = "document_figures"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Номер страницы в исходном файле — именно он уходит студенту.
    # 0 для DOCX, где страниц нет
    page_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # Порядковый номер иллюстрации на странице
    index_on_page: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    kind: Mapped[FigureKind] = mapped_column(
        Enum(FigureKind, name="figure_kind"),
        default=FigureKind.figure,
        nullable=False,
    )
    # Подпись как в книге: «Рис. 23.1», «Plate 8». None — рисунок без подписи
    label: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(String(1024))
    # Текст выносок внутри рисунка: названия структур, которые на нём обозначены
    labels: Mapped[list[str] | None] = mapped_column(ARRAY(Text))

    # Координаты на странице в точках PDF — для вырезания предпросмотра
    bbox: Mapped[list[float] | None] = mapped_column(ARRAY(Float))
    page_width: Mapped[float | None] = mapped_column(Float)
    page_height: Mapped[float | None] = mapped_column(Float)

    # Насколько уверенно это именно иллюстрация: 0.95 — нашлась подпись,
    # 0.5 — только картинка подходящего размера. Порог настраивается
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)

    # ID вложения в VK (photo-XXX_YYY): вырезанную однажды иллюстрацию
    # не грузим на серверы VK повторно
    vk_attachment_id: Mapped[str | None] = mapped_column(String(128))

    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embedding_dim))
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR)

    # Снять галочку, чтобы бот перестал ссылаться на конкретный рисунок
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    extra: Mapped[dict | None] = mapped_column(JSONB)

    # Имя в кавычках разрешает реестр SQLAlchemy — обратный импорт
    # Document сюда создал бы цикл
    document: Mapped["Document"] = relationship(  # noqa: F821, UP037
        back_populates="figures"
    )

    __table_args__ = (
        Index("ix_document_figures_doc_page", "document_id", "page_number"),
        Index(
            "ix_document_figures_doc_page_idx",
            "document_id",
            "page_number",
            "index_on_page",
            unique=True,
        ),
        Index("ix_document_figures_search", "search_vector", postgresql_using="gin"),
        Index(
            "ix_document_figures_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    def caption(self) -> str:
        """Как иллюстрация называется в одной строке."""
        parts = [p for p in (self.label, self.title) if p]
        if parts:
            return " ".join(parts)
        return {
            FigureKind.plate: "иллюстрация на всю страницу",
            FigureKind.page: "отсканированная страница",
            FigureKind.table: "таблица",
        }.get(self.kind, "рисунок без подписи")
