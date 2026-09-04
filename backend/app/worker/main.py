"""Воркер фоновых задач.

Запуск: arq app.worker.main.WorkerSettings

Здесь выполняется всё долгое: разбор учебников, OCR, расчёт эмбеддингов,
прогон контрольных наборов.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger, setup_logging
from app.db.session import db_session
from app.services import document_service, evaluation_service, image_service
from app.worker.queue import redis_settings

setup_logging()
log = get_logger("worker")


async def index_document(ctx: dict, document_id: int) -> None:
    log.info("task_index_document", document_id=document_id)
    async with db_session() as db:
        await document_service.index_document(db, document_id)


async def index_image(ctx: dict, image_id: int) -> None:
    async with db_session() as db:
        try:
            await image_service.index_image(db, image_id)
        except RuntimeError as exc:
            log.warning("task_index_image_failed", image_id=image_id, error=str(exc))


async def run_test_set(ctx: dict, run_id: int, overrides: dict[str, Any] | None = None) -> None:
    log.info("task_run_test_set", run_id=run_id)
    async with db_session() as db:
        await evaluation_service.run_test_set(db, run_id, overrides=overrides)


async def startup(ctx: dict) -> None:
    log.info("worker_started")


async def shutdown(ctx: dict) -> None:
    from app.llm.factory import close_all
    from app.rag.embeddings import close

    await close()
    await close_all()
    log.info("worker_stopped")


class WorkerSettings:
    functions = [index_document, index_image, run_test_set]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings()

    # Индексация упирается в сервис эмбеддингов на CPU — параллелить
    # сильнее смысла нет, только вырастет очередь на нём
    max_jobs = 2
    # Учебник на несколько сотен страниц с OCR идёт долго
    job_timeout = 60 * 60 * 3
    keep_result = 60 * 60 * 24
    max_tries = 2
