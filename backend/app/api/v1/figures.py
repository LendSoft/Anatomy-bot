"""Иллюстрации, найденные в учебных материалах.

Загрузки здесь нет и быть не может: иллюстрации извлекаются из самих
документов при индексации. Панель даёт их посмотреть, проверить разбор
подписей и отключить неудачно распознанные.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from app.api.deps import CurrentAdmin, DbSession
from app.models.document import Document
from app.models.figure import DocumentFigure, FigureKind
from app.schemas.common import MessageResponse, Page
from app.schemas.content import FigureOut, FigureUpdate
from app.services import figure_service

router = APIRouter(prefix="/figures", tags=["Иллюстрации материалов"])


def _to_out(figure: DocumentFigure, document_title: str | None = None) -> FigureOut:
    data = FigureOut.model_validate(figure)
    data.caption = figure.caption()
    data.document_title = document_title
    data.labels_count = len(figure.labels or [])
    data.is_indexed = figure.embedding is not None
    data.preview_url = f"/api/v1/figures/{figure.id}/preview"
    return data


@router.get("", response_model=Page[FigureOut])
async def list_figures(
    db: DbSession,
    _: CurrentAdmin,
    page: int = Query(1, ge=1),
    size: int = Query(24, ge=1, le=200),
    document_id: int | None = None,
    kind: FigureKind | None = None,
    page_number: int | None = Query(None, ge=0),
    search: str | None = None,
    min_confidence: float | None = Query(None, ge=0.0, le=1.0),
) -> Page[FigureOut]:
    query = select(DocumentFigure, Document.title).join(
        Document, Document.id == DocumentFigure.document_id
    )
    count_query = select(func.count(DocumentFigure.id))

    conditions = []
    if document_id is not None:
        conditions.append(DocumentFigure.document_id == document_id)
    if kind is not None:
        conditions.append(DocumentFigure.kind == kind)
    if page_number is not None:
        conditions.append(DocumentFigure.page_number == page_number)
    if min_confidence is not None:
        conditions.append(DocumentFigure.confidence >= min_confidence)
    if search:
        pattern = f"%{search}%"
        conditions.append(
            DocumentFigure.title.ilike(pattern) | DocumentFigure.label.ilike(pattern)
        )

    for condition in conditions:
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = (await db.execute(count_query)).scalar_one()
    rows = (
        await db.execute(
            query.order_by(
                DocumentFigure.document_id,
                DocumentFigure.page_number,
                DocumentFigure.index_on_page,
            )
            .offset((page - 1) * size)
            .limit(size)
        )
    ).all()

    return Page[FigureOut](
        items=[_to_out(figure, title) for figure, title in rows],
        total=total,
        page=page,
        size=size,
    )


@router.get("/{figure_id}", response_model=FigureOut)
async def get_figure(figure_id: int, db: DbSession, _: CurrentAdmin) -> FigureOut:
    figure = await db.get(DocumentFigure, figure_id)
    if figure is None:
        raise HTTPException(status_code=404, detail="Иллюстрация не найдена")

    document = await db.get(Document, figure.document_id)
    return _to_out(figure, document.title if document else None)


@router.patch("/{figure_id}", response_model=FigureOut)
async def update_figure(
    figure_id: int, payload: FigureUpdate, db: DbSession, _: CurrentAdmin
) -> FigureOut:
    """Правка разбора: подпись распознана неверно либо рисунок лишний."""
    figure = await db.get(DocumentFigure, figure_id)
    if figure is None:
        raise HTTPException(status_code=404, detail="Иллюстрация не найдена")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(figure, field, value)
    await db.commit()
    await db.refresh(figure)

    document = await db.get(Document, figure.document_id)
    return _to_out(figure, document.title if document else None)


@router.get("/{figure_id}/preview")
async def get_figure_preview(figure_id: int, db: DbSession) -> Response:
    """Вырезка иллюстрации из исходного файла.

    Без авторизации: ссылка на картинку уходит студенту вместе с ответом.
    Первое обращение вырезает фрагмент из PDF, дальше отдаётся из кэша.
    """
    figure = await db.get(DocumentFigure, figure_id)
    if figure is None or not figure.is_active:
        raise HTTPException(status_code=404, detail="Иллюстрация не найдена")

    path = await figure_service.preview_for(db, figure)
    if path is None or not Path(path).exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "Для этой иллюстрации нельзя построить предпросмотр: "
                "в файле нет её координат (так бывает с DOCX)"
            ),
        )

    # Вырезка детерминирована по координатам, поэтому её можно смело
    # держать в кэше браузера
    return FileResponse(
        path,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("/reindex/{document_id}", response_model=MessageResponse)
async def reembed_figures(
    document_id: int, db: DbSession, _: CurrentAdmin
) -> MessageResponse:
    """Пересчёт векторов иллюстраций без повторного разбора документа."""
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Документ не найден")

    count = await figure_service.embed_document_figures(db, document_id)
    return MessageResponse(detail=f"Пересчитано иллюстраций: {count}")
