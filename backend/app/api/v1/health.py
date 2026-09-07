"""Проверка состояния компонентов системы."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import CurrentAdmin, DbSession, get_redis
from app.core.config import settings
from app.llm.factory import get_llm
from app.rag import embeddings
from app.services import settings_service

router = APIRouter(tags=["Служебное"])


@router.get("/health")
async def health(db: DbSession) -> dict[str, Any]:
    """Лёгкая проверка для Docker healthcheck — только БД."""
    try:
        await db.execute(text("SELECT 1"))
        database_ok = True
    except Exception:  # noqa: BLE001
        database_ok = False

    return {
        "status": "ok" if database_ok else "degraded",
        "database": database_ok,
        "environment": settings.environment,
    }


@router.get("/health/full")
async def health_full(db: DbSession, _: CurrentAdmin) -> dict[str, Any]:
    """Развёрнутая проверка для админ-панели: БД, Redis, эмбеддинги, LLM."""
    result: dict[str, Any] = {}

    try:
        await db.execute(text("SELECT 1"))
        result["database"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        result["database"] = {"ok": False, "error": str(exc)}

    try:
        await get_redis().ping()
        result["redis"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        result["redis"] = {"ok": False, "error": str(exc)}

    embeddings_health = await embeddings.health()
    result["embeddings"] = {
        "ok": bool(embeddings_health.get("ready")),
        **embeddings_health,
    }

    llm = get_llm()
    try:
        llm_ok = await llm.health()
    except Exception:  # noqa: BLE001
        llm_ok = False
    result["llm"] = {
        "ok": llm_ok,
        "provider": llm.provider_name,
        "model": llm.model,
    }

    # Панель приоритетнее .env — так же, как для самого бота (app.vk.run.load_vk_config)
    vk_values = await settings_service.get_all(db, use_cache=False)
    vk_enabled = bool(settings_service.resolve(vk_values, "vk_enabled", settings.vk_enabled))
    vk_token = settings_service.resolve(vk_values, "vk_group_token", settings.vk_group_token)
    result["vk"] = {"enabled": vk_enabled, "configured": bool(vk_token)}
    result["status"] = "ok" if all(
        component.get("ok", True) for component in result.values() if isinstance(component, dict)
    ) else "degraded"

    return result
