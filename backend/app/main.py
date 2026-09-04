"""Точка входа FastAPI."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import close_redis
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.session import db_session
from app.llm.factory import close_all as close_llm_clients
from app.rag.embeddings import close as close_embeddings
from app.services import bootstrap
from app.worker.queue import close_pool

setup_logging()
log = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("api_starting", environment=settings.environment)
    try:
        async with db_session() as db:
            await bootstrap.run(db)
    except SQLAlchemyError:
        # Приложение поднимается и без этого: миграции могли ещё не пройти,
        # а healthcheck покажет реальное состояние
        log.exception("bootstrap_failed")

    yield

    await close_embeddings()
    await close_llm_clients()
    await close_pool()
    await close_redis()
    log.info("api_stopped")


app = FastAPI(
    title=settings.project_name,
    description="Образовательный бот по анатомии человека: API админ-панели и RAG-движка",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.monotonic()
    response = await call_next(request)
    duration_ms = int((time.monotonic() - started) * 1000)

    # Health-чеки идут каждые 15 секунд — не засоряем ими журнал
    if not request.url.path.endswith("/health"):
        log.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )

    response.headers["X-Process-Time-Ms"] = str(duration_ms)
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": "Ошибка в переданных данных", "errors": exc.errors()},
    )


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_error", path=request.url.path)
    # В проде текст исключения наружу не отдаём
    detail = (
        "Внутренняя ошибка сервера"
        if settings.is_production
        else f"{type(exc).__name__}: {exc}"
    )
    return JSONResponse(status_code=500, content={"detail": detail})


app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {"service": settings.project_name, "version": "1.0.0", "docs": "/docs"}
