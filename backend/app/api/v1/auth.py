"""Вход в админ-панель и управление учётками."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentAdmin, DbSession, Superuser
from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import AdminUser
from app.schemas.auth import (
    AdminUserCreate,
    AdminUserOut,
    LoginRequest,
    PasswordChange,
    TokenResponse,
)
from app.schemas.common import MessageResponse

router = APIRouter(prefix="/auth", tags=["Авторизация"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    admin = (
        await db.execute(select(AdminUser).where(AdminUser.email == payload.email))
    ).scalar_one_or_none()

    # Одинаковый ответ на неверный логин и неверный пароль — не подсказываем,
    # какие адреса зарегистрированы
    if admin is None or not verify_password(payload.password, admin.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный e-mail или пароль"
        )

    if not admin.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Учётная запись отключена")

    admin.last_login_at = datetime.now(UTC)
    await db.commit()

    return TokenResponse(
        access_token=create_access_token(
            admin.email, extra={"is_superuser": admin.is_superuser}
        ),
        expires_in_minutes=settings.access_token_expire_minutes,
    )


@router.get("/me", response_model=AdminUserOut)
async def me(admin: CurrentAdmin) -> AdminUser:
    return admin


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    payload: PasswordChange, admin: CurrentAdmin, db: DbSession
) -> MessageResponse:
    if not verify_password(payload.current_password, admin.hashed_password):
        raise HTTPException(status_code=400, detail="Текущий пароль указан неверно")

    admin.hashed_password = hash_password(payload.new_password)
    await db.commit()
    return MessageResponse(detail="Пароль изменён")


@router.get("/users", response_model=list[AdminUserOut])
async def list_users(db: DbSession, _: Superuser) -> list[AdminUser]:
    return list(
        (await db.execute(select(AdminUser).order_by(AdminUser.id))).scalars().all()
    )


@router.post("/users", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED)
async def create_user(payload: AdminUserCreate, db: DbSession, _: Superuser) -> AdminUser:
    exists = (
        await db.execute(select(AdminUser).where(AdminUser.email == payload.email))
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=409, detail="Пользователь с таким e-mail уже есть")

    admin = AdminUser(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        is_superuser=payload.is_superuser,
    )
    db.add(admin)
    await db.commit()
    await db.refresh(admin)
    return admin


@router.delete("/users/{user_id}", response_model=MessageResponse)
async def delete_user(user_id: int, db: DbSession, current: Superuser) -> MessageResponse:
    if user_id == current.id:
        raise HTTPException(status_code=400, detail="Нельзя удалить собственную учётную запись")

    admin = (
        await db.execute(select(AdminUser).where(AdminUser.id == user_id))
    ).scalar_one_or_none()
    if admin is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    await db.delete(admin)
    await db.commit()
    return MessageResponse(detail="Пользователь удалён")
