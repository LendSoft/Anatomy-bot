"""Извлечение текста из учебных материалов.

Порядок для PDF:
  1. pypdf — быстро и достаточно для книг с текстовым слоем;
  2. если текста почти нет, документ считается сканом и идёт в OCR;
  3. docling — когда нужна структура (заголовки, таблицы).

Номера страниц сохраняются на каждом шаге: без них не получится указать
источник так, как требует ТЗ.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.logging import get_logger

log = get_logger(__name__)

# Ниже этого числа символов на страницу считаем, что текстового слоя нет
MIN_CHARS_PER_PAGE = 80


@dataclass
class PageText:
    page_number: int
    text: str
    # Заголовки, найденные на странице — используются как метка фрагмента
    headings: list[str] = field(default_factory=list)


@dataclass
class ParsedDocument:
    pages: list[PageText]
    used_ocr: bool = False
    parser: str = "pypdf"

    @property
    def total_chars(self) -> int:
        return sum(len(p.text) for p in self.pages)


class ParsingError(RuntimeError):
    pass


# ------------------------------------------------------------------ утилиты

_HYPHEN_BREAK = re.compile(r"(\w)-\s*\n\s*(\w)")
_MULTI_SPACE = re.compile(r"[ \t]+")
_MULTI_NEWLINE = re.compile(r"\n{3,}")
# Строка целиком из заглавных или похожая на нумерованный заголовок раздела
_HEADING = re.compile(
    r"^(?:[А-ЯЁA-Z][А-ЯЁA-Z\s\-,\.]{6,80}|"
    r"(?:\d+\.){1,3}\s+[А-ЯЁA-Z][^\n]{3,80})$"
)


def clean_text(raw: str) -> str:
    """Убирает переносы по слогам и лишние пробелы.

    В учебниках слова регулярно разорваны переносом в конце строки —
    без склейки «плече-вая» не найдётся ни поиском, ни эмбеддингом.
    """
    text = raw.replace("\xa0", " ").replace("­", "")
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = _MULTI_SPACE.sub(" ", text)
    text = _MULTI_NEWLINE.sub("\n\n", text)
    return text.strip()


def detect_headings(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.split("\n")
        if _HEADING.match(line.strip())
    ]


# -------------------------------------------------------------------- PDF


def parse_pdf_text_layer(path: Path) -> ParsedDocument:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages: list[PageText] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 — одна битая страница не должна ронять книгу
            log.warning("pdf_page_extract_failed", page=i, error=str(exc))
            raw = ""
        text = clean_text(raw)
        pages.append(PageText(page_number=i, text=text, headings=detect_headings(text)))

    return ParsedDocument(pages=pages, parser="pypdf")


def parse_pdf_ocr(path: Path, languages: str = "rus+eng") -> ParsedDocument:
    """Распознавание отсканированных страниц.

    Медленно (единицы секунд на страницу), поэтому вызывается только когда
    текстового слоя действительно нет.
    """
    import pytesseract
    from pdf2image import convert_from_path

    pages: list[PageText] = []
    # Постранично, чтобы книга на 800 страниц не съела всю память
    from pypdf import PdfReader

    total = len(PdfReader(str(path)).pages)

    for i in range(1, total + 1):
        try:
            images = convert_from_path(str(path), dpi=300, first_page=i, last_page=i)
            raw = pytesseract.image_to_string(images[0], lang=languages)
        except Exception as exc:  # noqa: BLE001
            log.warning("ocr_page_failed", page=i, error=str(exc))
            raw = ""
        text = clean_text(raw)
        pages.append(PageText(page_number=i, text=text, headings=detect_headings(text)))

        if i % 25 == 0:
            log.info("ocr_progress", page=i, total=total)

    return ParsedDocument(pages=pages, used_ocr=True, parser="tesseract")


def parse_pdf(path: Path, ocr_enabled: bool = True) -> ParsedDocument:
    doc = parse_pdf_text_layer(path)

    if not doc.pages:
        raise ParsingError("PDF не содержит страниц")

    avg_chars = doc.total_chars / len(doc.pages)
    if avg_chars >= MIN_CHARS_PER_PAGE:
        return doc

    if not ocr_enabled:
        raise ParsingError(
            "В PDF нет текстового слоя (похоже на скан), а OCR отключён в настройках"
        )

    log.info("pdf_looks_scanned", avg_chars=round(avg_chars, 1), pages=len(doc.pages))
    return parse_pdf_ocr(path)


# -------------------------------------------------------------------- DOCX


def parse_docx(path: Path) -> ParsedDocument:
    """DOCX не разбит на страницы — разрывы страниц там условны.

    Собираем весь текст, разметку заголовков берём из стилей Word
    (Heading 1..9) и складываем в одну «страницу»: для цитирования
    важнее раздел, чем номер страницы, которого в файле попросту нет.
    """
    import docx

    document = docx.Document(str(path))
    parts: list[str] = []
    headings: list[str] = []

    for para in document.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = (para.style.name or "").lower()
        if style.startswith("heading") or style.startswith("заголовок"):
            headings.append(text)
            parts.append(f"\n\n## {text}\n")
        else:
            parts.append(text)

    # Таблицы в методичках часто содержат классификации — теряем их зря
    for table in document.tables:
        rows = [
            " | ".join(cell.text.strip() for cell in row.cells)
            for row in table.rows
            if any(cell.text.strip() for cell in row.cells)
        ]
        if rows:
            parts.append("\n" + "\n".join(rows) + "\n")

    text = clean_text("\n".join(parts))
    return ParsedDocument(
        pages=[PageText(page_number=1, text=text, headings=headings)],
        parser="python-docx",
    )


def parse_txt(path: Path) -> ParsedDocument:
    text = clean_text(path.read_text(encoding="utf-8", errors="replace"))
    return ParsedDocument(
        pages=[PageText(page_number=1, text=text, headings=detect_headings(text))],
        parser="plain",
    )


def parse(path: Path, ocr_enabled: bool = True) -> ParsedDocument:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(path, ocr_enabled=ocr_enabled)
    if suffix in (".docx", ".doc"):
        if suffix == ".doc":
            raise ParsingError(
                "Формат .doc не поддерживается — пересохраните файл как .docx"
            )
        return parse_docx(path)
    if suffix in (".txt", ".md"):
        return parse_txt(path)
    raise ParsingError(f"Неподдерживаемый формат файла: {suffix}")
