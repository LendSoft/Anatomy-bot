"""Постановка задач в очередь ARQ из веб-процесса."""

from __future__ import annotations

import asyncio
from typing import Any

from arq import create_pool
from arq.constants import default_queue_name, in_progress_key_prefix
from arq.connections import ArqRedis, RedisSettings
from arq.jobs import Job

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_pool: ArqRedis | None = None
DOCUMENT_JOB_FUNCTIONS = {"index_document", "embed_figures"}


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


async def document_jobs(document_id: int) -> list[Job]:
    pool = await get_pool()
    queued_ids = await pool.zrange(default_queue_name, 0, -1)
    active_keys = await pool.keys(f"{in_progress_key_prefix}*")
    job_ids = {
        job_id.decode() if isinstance(job_id, bytes) else str(job_id)
        for job_id in queued_ids
    }
    job_ids.update(
        key.decode().removeprefix(in_progress_key_prefix)
        if isinstance(key, bytes)
        else str(key).removeprefix(in_progress_key_prefix)
        for key in active_keys
    )

    matches = []
    for job_id in job_ids:
        job = Job(job_id, pool)
        info = await job.info()
        if (
            info is not None
            and info.function in DOCUMENT_JOB_FUNCTIONS
            and info.args
            and info.args[0] == document_id
        ):
            matches.append(job)
    return matches


async def has_document_jobs(document_id: int) -> bool:
    return bool(await document_jobs(document_id))


async def abort_document_jobs(document_id: int) -> int:
    try:
        jobs = await document_jobs(document_id)
    except Exception as exc:  # noqa: BLE001 — удаление всё равно должно завершиться
        log.error("document_jobs_lookup_failed", document_id=document_id, error=str(exc))
        return 0

    results = await asyncio.gather(
        *(job.abort(timeout=5) for job in jobs), return_exceptions=True
    )
    aborted = 0
    for job, result in zip(jobs, results, strict=True):
        if isinstance(result, BaseException):
            log.warning(
                "document_job_abort_failed",
                document_id=document_id,
                job_id=job.job_id,
                error=str(result),
            )
        elif result:
            aborted += 1
    return aborted


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
