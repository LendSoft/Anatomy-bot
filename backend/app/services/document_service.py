"""Индексация учебных материалов.

Тяжёлая часть (парсинг, OCR, эмбеддинги) выполняется в воркере ARQ:
разбор учебника на 800 страниц занимает минуты, держать на этом
HTTP-запрос нельзя.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.figure import DocumentFigure
from app.rag import embeddings, parsers
from app.rag.chunking import chunk_document
from app.services import figure_service, settings_service

log = get_logger(__name__)

# Батч для эмбеддингов: больше — быстрее, но на CPU растёт задержка и память
EMBED_BATCH = 32


async def _set_status(
    db: AsyncSession,
    document_id: int,
    status: DocumentStatus,
    *,
    progress: int | None = None,
    error: str | None = None,
) -> None:
    values: dict = {"status": status}
    if progress is not None:
        values["progress"] = progress
    if error is not None:
        values["error_message"] = error
    await db.execute(update(Document).where(Document.id == document_id).values(**values))
    await db.commit()


async def _document_exists(db: AsyncSession, document_id: int) -> bool:
    return (
        await db.execute(select(Document.id).where(Document.id == document_id))
    ).scalar_one_or_none() is not None


async def _save_figures(
    db: AsyncSession, document_id: int, parsed: parsers.ParsedDocument
) -> int:
    """Сохраняет найденные в документе иллюстрации.

    Нумерация внутри страницы идёт по порядку разбора — она же входит в
    уникальный индекс, поэтому считается здесь, а не в парсере.
    """
    saved = 0
    for page in parsed.pages:
        for index_on_page, figure in enumerate(page.figures):
            db.add(figure_service.to_model(document_id, figure, index_on_page))
            saved += 1

        # Коммитим постранично: в атласе на две тысячи страниц держать все
        # объекты в сессии незачем
        if saved and saved % 200 == 0:
            await db.commit()

    await db.commit()
    log.info("figures_saved", document_id=document_id, figures=saved)
    return saved


async def index_document(db: AsyncSession, document_id: int) -> None:
    """Полный цикл индексации одного документа."""
    document = (
        await db.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()

    if document is None:
        log.warning("index_document_not_found", document_id=document_id)
        return

    cfg = await settings_service.get_all(db, use_cache=False)
    path = Path(document.stored_path)

    if not path.exists():
        await _set_status(
            db, document_id, DocumentStatus.failed, error=f"Файл не найден: {path}"
        )
        return

    try:
        # При первом запуске сервис эмбеддингов ещё скачивает веса моделей.
        # Ждём его, иначе документ уйдёт в ошибку из-за того, что система
        # просто не успела прогреться.
        if not await embeddings.wait_ready():
            raise RuntimeError(
                "Сервис эмбеддингов не готов. Проверьте его состояние в разделе "
                "«Система» и переиндексируйте документ."
            )

        # ------------------------------------------------------- парсинг
        await _set_status(db, document_id, DocumentStatus.parsing, progress=5)
        log.info("parsing_started", document_id=document_id, file=document.original_filename)

        cancel_event = threading.Event()
        try:
            parsed = await asyncio.to_thread(
                parsers.parse,
                path,
                ocr_enabled=bool(cfg["ocr_enabled"]),
                should_cancel=cancel_event.is_set,
            )
        except asyncio.CancelledError:
            cancel_event.set()
            raise

        if not await _document_exists(db, document_id):
            log.info("indexing_cancelled_document_deleted", document_id=document_id)
            return

        if not parsed.total_chars:
            raise parsers.ParsingError(
                "Из файла не удалось извлечь текст. Если это скан, включите OCR в настройках."
            )

        # -------------------------------------------------------- нарезка
        await _set_status(db, document_id, DocumentStatus.chunking, progress=35)
        chunks = chunk_document(
            parsed,
            chunk_size=int(cfg["chunk_size"]),
            chunk_overlap=int(cfg["chunk_overlap"]),
        )

        if not chunks:
            raise parsers.ParsingError("После нарезки не осталось ни одного фрагмента")

        if not await _document_exists(db, document_id):
            log.info("indexing_cancelled_document_deleted", document_id=document_id)
            return

        log.info(
            "chunking_done",
            document_id=document_id,
            pages=len(parsed.pages),
            chunks=len(chunks),
            ocr=parsed.used_ocr,
        )

        # Переиндексация: старые фрагменты и иллюстрации убираем целиком
        await db.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        await db.execute(
            delete(DocumentFigure).where(DocumentFigure.document_id == document_id)
        )
        await db.commit()
        # Координаты рисунков после нового разбора другие — вырезанные по
        # старым предпросмотры показывали бы не то, что подписано
        figure_service.clear_previews(document_id)

        figures_saved = await _save_figures(db, document_id, parsed)

        # ------------------------------------------------------ эмбеддинги
        await _set_status(db, document_id, DocumentStatus.embedding, progress=45)

        for start in range(0, len(chunks), EMBED_BATCH):
            if not await _document_exists(db, document_id):
                log.info("indexing_cancelled_document_deleted", document_id=document_id)
                return
            batch = chunks[start : start + EMBED_BATCH]
            # Заголовок в тексте эмбеддинга помогает попадать в нужный раздел
            texts = [
                f"{c.heading}\n{c.content}" if c.heading else c.content for c in batch
            ]
            vectors = await embeddings.embed(texts, kind="document")

            if not await _document_exists(db, document_id):
                log.info("indexing_cancelled_document_deleted", document_id=document_id)
                return

            db.add_all(
                [
                    DocumentChunk(
                        document_id=document_id,
                        chunk_index=chunk.index,
                        content=chunk.content,
                        heading=chunk.heading,
                        page_from=chunk.page_from,
                        page_to=chunk.page_to,
                        token_count=chunk.approx_tokens,
                        embedding=vector,
                    )
                    for chunk, vector in zip(batch, vectors, strict=True)
                ]
            )
            await db.commit()

            # На эмбеддинги фрагментов отводим 45–90%, остаток — иллюстрациям
            progress = 45 + int(45 * (start + len(batch)) / len(chunks))
            await _set_status(db, document_id, DocumentStatus.embedding, progress=progress)

        # ------------------------------------------- эмбеддинги иллюстраций
        # Нужны, чтобы находить рисунок по вопросу напрямую: у страницы
        # атласа текста нет, кроме надписей на самом изображении
        if figures_saved:
            if not await _document_exists(db, document_id):
                log.info("indexing_cancelled_document_deleted", document_id=document_id)
                return
            await _set_status(db, document_id, DocumentStatus.embedding, progress=90)
            try:
                await figure_service.embed_document_figures(db, document_id)
            except Exception as exc:  # noqa: BLE001 — ссылки на рисунки работают и без вектора
                log.warning(
                    "figure_embedding_failed", document_id=document_id, error=str(exc)
                )
                await db.rollback()

        # --------------------------------------------------------- готово
        if not await _document_exists(db, document_id):
            log.info("indexing_cancelled_document_deleted", document_id=document_id)
            return
        await db.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(
                status=DocumentStatus.ready,
                progress=100,
                error_message=None,
                pages_count=len(parsed.pages),
                chunks_count=len(chunks),
                figures_count=figures_saved,
                indexed_at=datetime.now(UTC),
                extra={
                    "parser": parsed.parser,
                    "used_ocr": parsed.used_ocr,
                    "figures": figures_saved,
                },
            )
        )
        await db.commit()
        log.info(
            "indexing_done",
            document_id=document_id,
            chunks=len(chunks),
            figures=figures_saved,
        )

    except Exception as exc:  # noqa: BLE001 — ошибку нужно показать в админке
        log.exception("indexing_failed", document_id=document_id)
        await db.rollback()
        await _set_status(db, document_id, DocumentStatus.failed, error=str(exc)[:2000])


async def delete_document(db: AsyncSession, document_id: int) -> bool:
    from app.services import storage
    from app.worker.queue import abort_document_jobs

    document = (
        await db.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()
    if document is None:
        return False

    stored_path = document.stored_path
    await db.rollback()
    await abort_document_jobs(document_id)

    document = await db.get(Document, document_id)
    if document is None:
        return False

    await db.delete(document)  # фрагменты и иллюстрации уходят каскадом
    await db.commit()

    storage.delete_file(stored_path)
    figure_service.clear_previews(document_id)
    return True
