"""Зависимости FastAPI: текущий администратор, БД, Redis."""

from __future__ import annotations

from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import AdminUser

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def get_current_admin(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> AdminUser:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Требуется авторизация",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise unauthorized

    payload = decode_access_token(credentials.credentials)
    if payload is None or not payload.get("sub"):
        raise unauthorized

    admin = (
        await db.execute(select(AdminUser).where(AdminUser.email == payload["sub"]))
    ).scalar_one_or_none()

    if admin is None or not admin.is_active:
        raise unauthorized

    return admin


CurrentAdmin = Annotated[AdminUser, Depends(get_current_admin)]


async def require_superuser(admin: CurrentAdmin) -> AdminUser:
    if not admin.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Действие доступно только суперпользователю",
        )
    return admin


Superuser = Annotated[AdminUser, Depends(require_superuser)]
