"""Первоначальное наполнение базы при старте приложения.

Создаёт учётку администратора и активные версии промптов, если их ещё
нет. Работает идемпотентно: повторный запуск ничего не портит.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import hash_password
from app.models.prompt import Prompt, PromptKind
from app.models.user import AdminUser
from app.rag import prompts as P

log = get_logger(__name__)

_PROMPT_DEFAULTS: list[tuple[PromptKind, str, str, list | None]] = [
    (PromptKind.system, "Системный промпт", P.DEFAULT_SYSTEM_PROMPT, None),
    (
        PromptKind.reference_answers,
        "Идеальные ответы",
        "Примеры ответов, которые модель берёт за образец формата и полноты.",
        P.DEFAULT_REFERENCE_ANSWERS,
    ),
    (PromptKind.judge, "Промпт судьи", P.DEFAULT_JUDGE_PROMPT, None),
    (
        PromptKind.query_rewrite,
        "Переформулировка запроса",
        P.DEFAULT_QUERY_REWRITE_PROMPT,
        None,
    ),
]


async def ensure_admin(db: AsyncSession) -> None:
    count = (await db.execute(select(func.count(AdminUser.id)))).scalar_one()
    if count:
        return

    admin = AdminUser(
        email=settings.first_admin_email,
        hashed_password=hash_password(settings.first_admin_password),
        full_name="Администратор",
        is_superuser=True,
    )
    db.add(admin)
    await db.commit()

    log.info("first_admin_created", email=settings.first_admin_email)
    if settings.first_admin_password in ("admin", "change_me_admin_password"):
        log.warning(
            "Пароль администратора оставлен по умолчанию — смените его "
            "в разделе «Настройки» сразу после первого входа"
        )


async def ensure_prompts(db: AsyncSession) -> None:
    for kind, name, content, examples in _PROMPT_DEFAULTS:
        exists = (
            await db.execute(select(func.count(Prompt.id)).where(Prompt.kind == kind))
        ).scalar_one()
        if exists:
            continue

        db.add(
            Prompt(
                kind=kind,
                version=1,
                name=name,
                content=content,
                examples=examples,
                is_active=True,
                created_by="system",
                comment="Создано автоматически при первом запуске",
            )
        )
        log.info("default_prompt_created", kind=kind.value)

    await db.commit()


async def run(db: AsyncSession) -> None:
    await ensure_admin(db)
    await ensure_prompts(db)
