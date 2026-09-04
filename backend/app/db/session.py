"""Асинхронный engine и фабрика сессий."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,      # соединения переживают перезапуск Postgres
    pool_size=10,
    max_overflow=20,
    pool_recycle=1800,
)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # объекты остаются пригодны после commit
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Зависимость FastAPI."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Для воркера и VK-бота, где механизма зависимостей нет."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
