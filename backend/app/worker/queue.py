"""Постановка задач в очередь ARQ из веб-процесса."""

from __future__ import annotations

from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_pool: ArqRedis | None = None


def redis_settings() -> RedisSettings:
    return RedisSettings(
        host=settings.redis_host, port=settings.redis_port, database=settings.redis_db
    )


async def get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings())
    return _pool


async def enqueue(task_name: str, *args: Any, **kwargs: Any) -> str | None:
    """Ставит задачу в очередь.

    Отказ очереди не должен ронять запрос: документ останется в статусе
    pending, и его можно переиндексировать вручную из админки.
    """
    try:
        pool = await get_pool()
        job = await pool.enqueue_job(task_name, *args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        log.error("enqueue_failed", task=task_name, error=str(exc))
        return None

    log.info("task_enqueued", task=task_name, job_id=job.job_id if job else None)
    return job.job_id if job else None


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
