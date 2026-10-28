"""Воркер фоновых задач.

Запуск: arq app.worker.main.WorkerSettings

Здесь выполняется всё долгое: разбор учебников, OCR, расчёт эмбеддингов,
прогон контрольных наборов.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger, setup_logging
from app.db.session import db_session
from app.services import document_service, evaluation_service, figure_service
from app.worker.queue import redis_settings

setup_logging()
log = get_logger("worker")


async def index_document(ctx: dict, document_id: int) -> None:
    log.info("task_index_document", document_id=document_id)
    async with db_session() as db:
        await document_service.index_document(db, document_id)


async def embed_figures(ctx: dict, document_id: int) -> None:
    """Пересчёт векторов иллюстраций документа.

    Отдельная задача нужна для случая, когда документ уже разобран, а
    векторы рисунков посчитать не удалось — например, сервис эмбеддингов
    в тот момент ещё грузил модели.
    """
    async with db_session() as db:
        try:
            await figure_service.embed_document_figures(db, document_id)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "task_embed_figures_failed", document_id=document_id, error=str(exc)
            )


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
    functions = [index_document, embed_figures, run_test_set]
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
