"""Схемы документов, изображений, промптов, настроек и словаря терминов."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.document import DocumentStatus
from app.models.figure import FigureKind
from app.models.prompt import PromptKind

# ---------------------------------------------------------------- документы


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    authors: str | None
    edition: str | None
    year: int | None
    section: str | None
    original_filename: str
    mime_type: str | None
    size_bytes: int
    status: DocumentStatus
    error_message: str | None
    progress: int
    pages_count: int
    chunks_count: int
    figures_count: int
    is_active: bool
    indexed_at: datetime | None
    created_at: datetime
    extra: dict | None


class DocumentUpdate(BaseModel):
    title: str | None = Field(None, max_length=512)
    authors: str | None = Field(None, max_length=512)
    edition: str | None = Field(None, max_length=255)
    year: int | None = Field(None, ge=1800, le=2100)
    section: str | None = Field(None, max_length=255)
    is_active: bool | None = None


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chunk_index: int
    content: str
    heading: str | None
    page_from: int | None
    page_to: int | None
    token_count: int


# -------------------------------------------------------------- иллюстрации


class FigureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    page_number: int
    index_on_page: int
    kind: FigureKind
    label: str | None
    title: str | None
    labels: list[str] | None
    confidence: float
    is_active: bool
    created_at: datetime

    # Вычисляемые поля для панели
    caption: str = ""
    document_title: str | None = None
    labels_count: int = 0
    is_indexed: bool = False
    preview_url: str | None = None


class FigureUpdate(BaseModel):
    """Правка разбора вручную.

    Менять можно только подпись и признак активности: координаты и
    страница берутся из файла, править их бессмысленно.
    """

    label: str | None = Field(None, max_length=64)
    title: str | None = Field(None, max_length=1024)
    is_active: bool | None = None


# ------------------------------------------------------------------ промпты


class PromptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: PromptKind
    version: int
    name: str | None
    content: str
    examples: list[dict] | None
    is_active: bool
    created_by: str | None
    comment: str | None
    created_at: datetime


class PromptCreate(BaseModel):
    kind: PromptKind
    content: str = Field(..., min_length=1)
    name: str | None = Field(None, max_length=255)
    examples: list[dict] | None = None
    comment: str | None = None
    # Новая версия сразу становится активной — обычный сценарий правки
    activate: bool = True


# ---------------------------------------------------------------- настройки


class SettingsUpdate(BaseModel):
    values: dict[str, Any]


class SettingsResponse(BaseModel):
    values: dict[str, Any]
    schema_: list[dict[str, Any]] = Field(..., alias="schema")

    model_config = ConfigDict(populate_by_name=True)


# ------------------------------------------------------------ словарь терминов


class TermOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    term_ru: str
    term_lat: str | None
    synonyms: list[str] | None
    section: str | None
    definition: str | None
    is_active: bool


class TermCreate(BaseModel):
    term_ru: str = Field(..., max_length=255)
    term_lat: str | None = Field(None, max_length=255)
    synonyms: list[str] | None = None
    section: str | None = Field(None, max_length=255)
    definition: str | None = None
