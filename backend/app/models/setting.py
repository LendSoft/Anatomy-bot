"""Runtime-настройки, которые администратор меняет из панели.

Ключ-значение в JSONB: температура, top_k, пороги релевантности, размер
чанка и прочее. Значения по умолчанию и описания полей лежат в
app/services/settings_service.py — там же живёт валидация.
"""

from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AppSetting(Base, TimestampMixin):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(String(255))
