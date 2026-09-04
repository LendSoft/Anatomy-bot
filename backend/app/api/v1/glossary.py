"""Словарь анатомических терминов ru ↔ lat."""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert

from app.api.deps import CurrentAdmin, DbSession
from app.models.glossary import AnatomyTerm
from app.schemas.common import MessageResponse, Page
from app.schemas.content import TermCreate, TermOut

router = APIRouter(prefix="/glossary", tags=["Словарь терминов"])


@router.get("", response_model=Page[TermOut])
async def list_terms(
    db: DbSession,
    _: CurrentAdmin,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    search: str | None = None,
    section: str | None = None,
) -> Page[TermOut]:
    query = select(AnatomyTerm)
    count_query = select(func.count(AnatomyTerm.id))

    conditions = []
    if search:
        pattern = f"%{search}%"
        conditions.append(
            or_(AnatomyTerm.term_ru.ilike(pattern), AnatomyTerm.term_lat.ilike(pattern))
        )
    if section:
        conditions.append(AnatomyTerm.section == section)

    for condition in conditions:
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = (await db.execute(count_query)).scalar_one()
    rows = (
        await db.execute(
            query.order_by(AnatomyTerm.term_ru).offset((page - 1) * size).limit(size)
        )
    ).scalars().all()

    return Page[TermOut](
        items=[TermOut.model_validate(row) for row in rows],
        total=total,
        page=page,
        size=size,
    )


@router.post("", response_model=TermOut, status_code=status.HTTP_201_CREATED)
async def create_term(payload: TermCreate, db: DbSession, _: CurrentAdmin) -> AnatomyTerm:
    term = AnatomyTerm(**payload.model_dump())
    db.add(term)
    try:
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — нарушение уникальности пары ru+lat
        await db.rollback()
        raise HTTPException(status_code=409, detail="Такой термин уже есть") from exc

    await db.refresh(term)
    return term


@router.post("/import", response_model=MessageResponse)
async def import_terms(
    db: DbSession, _: CurrentAdmin, file: UploadFile = File(...)
) -> MessageResponse:
    """Импорт словаря из CSV: term_ru, term_lat, synonyms, section, definition.

    Синонимы — через точку с запятой внутри ячейки. Повторный импорт
    обновляет существующие записи, а не падает на дубликатах.
    """
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    dialect = csv.Sniffer().sniff(raw[:2048], delimiters=",;\t") if raw.strip() else csv.excel
    reader = csv.DictReader(io.StringIO(raw), dialect=dialect)

    if not reader.fieldnames or "term_ru" not in reader.fieldnames:
        raise HTTPException(status_code=400, detail="В файле должна быть колонка «term_ru»")

    processed = 0
    for row in reader:
        term_ru = (row.get("term_ru") or "").strip()
        if not term_ru:
            continue

        synonyms_raw = (row.get("synonyms") or "").strip()
        synonyms = [s.strip() for s in synonyms_raw.split(";") if s.strip()] or None

        values = {
            "term_ru": term_ru,
            "term_lat": (row.get("term_lat") or "").strip() or None,
            "synonyms": synonyms,
            "section": (row.get("section") or "").strip() or None,
            "definition": (row.get("definition") or "").strip() or None,
        }

        await db.execute(
            insert(AnatomyTerm)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["term_ru", "term_lat"],
                set_={
                    "synonyms": values["synonyms"],
                    "section": values["section"],
                    "definition": values["definition"],
                },
            )
        )
        processed += 1

    await db.commit()
    return MessageResponse(detail=f"Обработано терминов: {processed}")


@router.delete("/{term_id}", response_model=MessageResponse)
async def delete_term(term_id: int, db: DbSession, _: CurrentAdmin) -> MessageResponse:
    term = await db.get(AnatomyTerm, term_id)
    if term is None:
        raise HTTPException(status_code=404, detail="Термин не найден")
    await db.delete(term)
    await db.commit()
    return MessageResponse(detail="Термин удалён")
