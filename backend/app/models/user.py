"""Администраторы панели и пользователи VK."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AdminUser(Base, TimestampMixin):
    """Учётка для входа в админ-панель."""

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VkUser(Base, TimestampMixin):
    """Студент, пишущий боту во ВКонтакте.

    Персональные данные не храним — только идентификатор сообщества VK
    и агрегаты для статистики.
    """

    __tablename__ = "vk_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vk_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    messages_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
