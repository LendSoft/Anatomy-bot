"""Сборка всех роутеров версии v1."""

from fastapi import APIRouter

from app.api.v1 import (
    auth,
    chat,
    documents,
    figures,
    glossary,
    health,
    logs,
    prompts,
    settings_api,
    stats,
    testing,
)

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(documents.router)
api_router.include_router(figures.router)
api_router.include_router(prompts.router)
api_router.include_router(settings_api.router)
api_router.include_router(chat.router)
api_router.include_router(logs.router)
api_router.include_router(stats.router)
api_router.include_router(testing.router)
api_router.include_router(glossary.router)
