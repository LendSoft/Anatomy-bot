"""Runtime-настройки бота."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentAdmin, DbSession
from app.schemas.content import SettingsResponse, SettingsUpdate
from app.services import settings_service

router = APIRouter(prefix="/settings", tags=["Настройки"])


@router.get("", response_model=SettingsResponse)
async def get_settings(db: DbSession, _: CurrentAdmin) -> SettingsResponse:
    """Текущие значения плюс описание полей — форма строится по нему.

    Ключи и токены наружу не отдаются: вместо них приходит маска.
    """
    return SettingsResponse(
        values=await settings_service.get_all_masked(db),
        schema=settings_service.describe(),
    )


@router.put("", response_model=SettingsResponse)
async def update_settings(
    payload: SettingsUpdate, db: DbSession, admin: CurrentAdmin
) -> SettingsResponse:
    try:
        await settings_service.update_many(db, payload.values, updated_by=admin.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SettingsResponse(
        values=await settings_service.get_all_masked(db),
        schema=settings_service.describe(),
    )


@router.post("/reset", response_model=SettingsResponse)
async def reset_settings(db: DbSession, admin: CurrentAdmin) -> SettingsResponse:
    await settings_service.update_many(
        db, dict(settings_service.DEFAULTS), updated_by=admin.email
    )
    return SettingsResponse(
        values=await settings_service.get_all_masked(db),
        schema=settings_service.describe(),
    )
