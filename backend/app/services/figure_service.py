"""Иллюстрации учебных материалов: индексация и предпросмотр.

Иллюстрации находит парсер при разборе документа (app/rag/figures.py),
здесь они сохраняются, получают вектор для поиска и по запросу
вырезаются из исходного файла.

Почему предпросмотр вырезается на ходу, а не складывается на диск при
индексации: в одном атласе Netter 2300 страниц, почти на каждой —
иллюстрация. Нарезать и хранить их все значит потратить часы индексации
и десятки гигабайт тома ради картинок, большую часть которых никто не
откроет. Вырезание одной страницы занимает порядка десятых долей
секунды, а повторные обращения отдаются из кэша на диске.
"""

from __future__ import annotations

import contextlib
import hashlib
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.document import Document
from app.models.figure import DocumentFigure, FigureKind
from app.rag import embeddings
from app.rag.figures import ExtractedFigure
from app.services import storage

log = get_logger(__name__)

PREVIEW_DIR = "figure-previews"

# Разрешение вырезанного фрагмента. 160 dpi хватает, чтобы прочесть
# выноски с названиями структур, и не раздувает картинку для VK
PREVIEW_DPI = 160
# Поля вокруг рисунка в точках: подпись и края выносок часто выходят
# за границы растра
PREVIEW_PADDING = 8.0

# Батч эмбеддингов для иллюстраций
EMBED_BATCH = 32


def to_model(
    document_id: int, figure: ExtractedFigure, index_on_page: int
) -> DocumentFigure:
    """Переводит найденную парсером иллюстрацию в строку таблицы.

    Вид приходит строкой: парсер не знает про типы БД. Неизвестное
    значение не должно ронять индексацию целой книги — такой рисунок
    записывается как обычный.
    """
    try:
        kind = FigureKind(figure.kind)
    except ValueError:
        log.warning("figure_unknown_kind", kind=figure.kind, document_id=document_id)
        kind = FigureKind.figure

    return DocumentFigure(
        document_id=document_id,
        page_number=figure.page_number,
        index_on_page=index_on_page,
        kind=kind,
        label=figure.label[:64] if figure.label else None,
        title=figure.title[:1024] if figure.title else None,
        labels=figure.labels or None,
        bbox=list(figure.bbox) if figure.bbox else None,
        page_width=figure.page_width,
        page_height=figure.page_height,
        confidence=figure.confidence,
    )


def index_text(figure: DocumentFigure, document: Document) -> str:
    """Текст, по которому иллюстрация находится.

    Название документа и раздел добавляются к подписи: вопрос студента
    часто содержит область («что в грудной клетке»), а подпись рисунка —
    только название структуры.
    """
    parts: list[str] = [figure.caption()]
    if document.section:
        parts.append(document.section)
    parts.append(document.title)
    if figure.labels:
        parts.append("; ".join(figure.labels))
    return "\n".join(part for part in parts if part)


async def embed_document_figures(db: AsyncSession, document_id: int) -> int:
    """Считает векторы для иллюстраций документа.

    Нужны, чтобы находить рисунок по вопросу напрямую, когда текст
    страницы в поиск не попал: у страницы атласа текста почти нет, кроме
    самих выносок.
    """
    document = (
        await db.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()
    if document is None:
        return 0

    rows = (
        await db.execute(
            select(DocumentFigure)
            .where(DocumentFigure.document_id == document_id)
            .order_by(DocumentFigure.page_number, DocumentFigure.index_on_page)
        )
    ).scalars().all()

    indexed = 0
    for start in range(0, len(rows), EMBED_BATCH):
        batch = rows[start : start + EMBED_BATCH]
        texts = [index_text(figure, document) for figure in batch]
        vectors = await embeddings.embed(texts, kind="document")
        for figure, vector in zip(batch, vectors, strict=True):
            figure.embedding = vector
        await db.commit()
        indexed += len(batch)

    log.info("figures_embedded", document_id=document_id, figures=indexed)
    return indexed


# ---------------------------------------------------------------- предпросмотр


def _document_preview_dir(document_id: int) -> Path:
    """Кэш раскладывается по документам — чтобы при переиндексации
    чистить только его картинки, не трогая остальные книги."""
    return storage.storage_root() / PREVIEW_DIR / str(document_id)


def _preview_path(figure: DocumentFigure) -> Path:
    """Путь в кэше. Имя зависит от координат: правка разметки рисунка
    даёт другое имя, и старая картинка не подменит новую."""
    key = f"{figure.page_number}:{figure.index_on_page}:{figure.bbox}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:32]
    directory = _document_preview_dir(figure.document_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{digest}.png"


def render_preview(figure: DocumentFigure, source_path: Path) -> Path | None:
    """Вырезает иллюстрацию из исходного документа.

    Возвращает путь к PNG или None, если вырезать нечего: у иллюстраций
    из DOCX нет ни страницы, ни координат.
    """
    import pymupdf

    cached = _preview_path(figure)
    if cached.exists():
        return cached

    if figure.page_number < 1 or not source_path.exists():
        return None
    if source_path.suffix.lower() != ".pdf":
        return None

    try:
        with pymupdf.open(str(source_path)) as doc:
            if figure.page_number > len(doc):
                return None
            page = doc[figure.page_number - 1]

            clip = None
            if figure.bbox and len(figure.bbox) == 4:
                clip = pymupdf.Rect(*figure.bbox) + (
                    -PREVIEW_PADDING,
                    -PREVIEW_PADDING,
                    PREVIEW_PADDING,
                    PREVIEW_PADDING,
                )
                # Выход за край листа PyMuPDF не прощает
                clip = clip & page.rect
                if clip.is_empty:
                    clip = None

            pixmap = page.get_pixmap(dpi=PREVIEW_DPI, clip=clip)
            pixmap.save(str(cached))
            return cached
    except Exception as exc:  # noqa: BLE001 — без предпросмотра ссылка всё равно работает
        log.warning(
            "figure_preview_failed",
            document_id=figure.document_id,
            page=figure.page_number,
            error=str(exc),
        )
        return None


async def preview_for(db: AsyncSession, figure: DocumentFigure) -> Path | None:
    document = await db.get(Document, figure.document_id)
    if document is None:
        return None
    return render_preview(figure, Path(document.stored_path))


def clear_previews(document_id: int) -> int:
    """Чистит кэш предпросмотров документа.

    Вызывается при переиндексации и удалении: координаты рисунков после
    нового разбора другие, а картинки по старым координатам только
    занимают место.
    """
    directory = _document_preview_dir(document_id)
    if not directory.exists():
        return 0

    removed = 0
    for path in directory.glob("*.png"):
        path.unlink(missing_ok=True)
        removed += 1

    # Пустой каталог документа не оставляем. Непустым он остаться может —
    # если параллельный запрос как раз вырезал новую картинку
    with contextlib.suppress(OSError):
        directory.rmdir()

    return removed


async def set_figures_count(db: AsyncSession, document_id: int, count: int) -> None:
    await db.execute(
        update(Document).where(Document.id == document_id).values(figures_count=count)
    )
    await db.commit()
