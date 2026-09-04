"""Промпты: просмотр версий, создание новой, откат на старую."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select, update

from app.api.deps import CurrentAdmin, DbSession
from app.core.logging import get_logger
from app.models.prompt import Prompt, PromptKind
from app.rag import prompts as defaults
from app.schemas.common import MessageResponse
from app.schemas.content import PromptCreate, PromptOut

log = get_logger(__name__)
router = APIRouter(prefix="/prompts", tags=["Промпты"])

DEFAULTS: dict[PromptKind, dict] = {
    PromptKind.system: {
        "content": defaults.DEFAULT_SYSTEM_PROMPT,
        "examples": None,
        "name": "Системный промпт",
    },
    PromptKind.reference_answers: {
        "content": "Эталонные ответы, которые модель берёт за образец формата и полноты.",
        "examples": defaults.DEFAULT_REFERENCE_ANSWERS,
        "name": "Идеальные ответы",
    },
    PromptKind.judge: {
        "content": defaults.DEFAULT_JUDGE_PROMPT,
        "examples": None,
        "name": "Промпт судьи",
    },
    PromptKind.query_rewrite: {
        "content": defaults.DEFAULT_QUERY_REWRITE_PROMPT,
        "examples": None,
        "name": "Переформулировка запроса",
    },
}


@router.get("", response_model=list[PromptOut])
async def list_prompts(
    db: DbSession, _: CurrentAdmin, kind: PromptKind | None = None, active_only: bool = False
) -> list[Prompt]:
    query = select(Prompt)
    if kind:
        query = query.where(Prompt.kind == kind)
    if active_only:
        query = query.where(Prompt.is_active.is_(True))

    return list(
        (await db.execute(query.order_by(Prompt.kind, Prompt.version.desc()))).scalars().all()
    )


@router.get("/active/{kind}", response_model=PromptOut)
async def get_active(kind: PromptKind, db: DbSession, _: CurrentAdmin) -> Prompt:
    prompt = (
        await db.execute(
            select(Prompt).where(Prompt.kind == kind, Prompt.is_active.is_(True))
        )
    ).scalar_one_or_none()

    if prompt is None:
        raise HTTPException(status_code=404, detail="Активная версия промпта не найдена")
    return prompt


@router.get("/defaults/{kind}", response_model=dict)
async def get_default(kind: PromptKind, _: CurrentAdmin) -> dict:
    """Заводское значение — чтобы было с чем сравнить свою правку."""
    return DEFAULTS.get(kind, {"content": "", "examples": None})


@router.post("", response_model=PromptOut, status_code=status.HTTP_201_CREATED)
async def create_prompt(
    payload: PromptCreate, db: DbSession, admin: CurrentAdmin
) -> Prompt:
    """Правка промпта — это всегда новая версия, старая остаётся для отката."""
    max_version = (
        await db.execute(
            select(func.coalesce(func.max(Prompt.version), 0)).where(
                Prompt.kind == payload.kind
            )
        )
    ).scalar_one()

    if payload.activate:
        await db.execute(
            update(Prompt).where(Prompt.kind == payload.kind).values(is_active=False)
        )

    prompt = Prompt(
        kind=payload.kind,
        version=max_version + 1,
        name=payload.name or DEFAULTS.get(payload.kind, {}).get("name"),
        content=payload.content,
        examples=payload.examples,
        comment=payload.comment,
        is_active=payload.activate,
        created_by=admin.email,
    )
    db.add(prompt)
    await db.commit()
    await db.refresh(prompt)

    log.info(
        "prompt_created", kind=payload.kind.value, version=prompt.version, by=admin.email
    )
    return prompt


@router.post("/{prompt_id}/activate", response_model=PromptOut)
async def activate_prompt(prompt_id: int, db: DbSession, admin: CurrentAdmin) -> Prompt:
    prompt = await db.get(Prompt, prompt_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail="Версия промпта не найдена")

    await db.execute(
        update(Prompt).where(Prompt.kind == prompt.kind).values(is_active=False)
    )
    prompt.is_active = True
    await db.commit()
    await db.refresh(prompt)

    log.info(
        "prompt_activated", kind=prompt.kind.value, version=prompt.version, by=admin.email
    )
    return prompt


@router.delete("/{prompt_id}", response_model=MessageResponse)
async def delete_prompt(prompt_id: int, db: DbSession, _: CurrentAdmin) -> MessageResponse:
    prompt = await db.get(Prompt, prompt_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail="Версия промпта не найдена")
    if prompt.is_active:
        raise HTTPException(
            status_code=400,
            detail="Нельзя удалить активную версию — сначала активируйте другую",
        )

    await db.delete(prompt)
    await db.commit()
    return MessageResponse(detail="Версия промпта удалена")
