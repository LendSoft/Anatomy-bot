"""Статистика для дашборда."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import CurrentAdmin, DbSession
from app.services import stats_service

router = APIRouter(prefix="/stats", tags=["Статистика"])


@router.get("/overview")
async def overview(
    db: DbSession, _: CurrentAdmin, days: int = Query(30, ge=1, le=365)
) -> dict[str, Any]:
    return await stats_service.overview(db, days=days)


@router.get("/daily")
async def daily(
    db: DbSession, _: CurrentAdmin, days: int = Query(30, ge=1, le=365)
) -> list[dict[str, Any]]:
    return await stats_service.daily(db, days=days)


@router.get("/top-questions")
async def top_questions(
    db: DbSession,
    _: CurrentAdmin,
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=100),
) -> list[dict[str, Any]]:
    return await stats_service.top_questions(db, days=days, limit=limit)


@router.get("/unanswered")
async def unanswered(
    db: DbSession,
    _: CurrentAdmin,
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """Вопросы, оставшиеся без ответа — показывает пробелы в базе материалов."""
    return await stats_service.unanswered(db, days=days, limit=limit)
