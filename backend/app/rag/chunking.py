"""Нарезка учебного текста на фрагменты.

Разбиение рекурсивное, с приоритетом естественных границ: абзац →
строка → предложение → слово. Разрыв посреди предложения ломает и
эмбеддинг, и цитату, поэтому жёсткий лимит применяется только когда
подходящей границы не нашлось.

Текст копится по разделам: смена заголовка закрывает накопленное, и
фрагмент никогда не смешивает материал из двух тем. Каждый фрагмент
помнит диапазон страниц и заголовок — из них собирается ссылка на
источник, которую требует ТЗ.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.rag.parsers import ParsedDocument

# Порядок разделителей от крупного к мелкому
SEPARATORS = ["\n\n", "\n", ". ", "; ", ", ", " "]

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

MIN_CHUNK_CHARS = 50


@dataclass
class Chunk:
    index: int
    content: str
    heading: str | None
    page_from: int | None
    page_to: int | None

    @property
    def approx_tokens(self) -> int:
        # Для русского с латинскими вставками ~3 символа на токен —
        # оценка нужна только для контроля размера контекста
        return max(1, len(self.content) // 3)


def _split_recursive(text: str, max_size: int, sep_index: int = 0) -> list[str]:
    """Режет текст на куски не длиннее max_size по естественным границам."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_size:
        return [text]

    if sep_index >= len(SEPARATORS):
        # Разделители кончились — режем по длине
        return [text[i : i + max_size] for i in range(0, len(text), max_size)]

    sep = SEPARATORS[sep_index]
    if sep not in text:
        return _split_recursive(text, max_size, sep_index + 1)

    pieces: list[str] = []
    current = ""
    for part in text.split(sep):
        candidate = f"{current}{sep}{part}" if current else part
        if len(candidate) <= max_size:
            current = candidate
            continue

        if current:
            pieces.append(current)
            current = ""
        if len(part) > max_size:
            # Отдельная часть сама по себе великовата — дробим мельче
            pieces.extend(_split_recursive(part, max_size, sep_index + 1))
        else:
            current = part

    if current.strip():
        pieces.append(current)

    return [p.strip() for p in pieces if p.strip()]


def _overlap_tail(text: str, overlap: int) -> str:
    """Хвост фрагмента для перекрытия, по возможности с границы предложения."""
    if overlap <= 0:
        return ""
    if len(text) <= overlap:
        return text

    tail = text[-overlap:]
    sentences = _SENTENCE_END.split(tail)
    if len(sentences) > 1:
        # Первое предложение почти наверняка обрезано — выбрасываем его
        return " ".join(sentences[1:]).strip()
    return tail.strip()


def _split_with_overlap(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Нарезка с перекрытием: к каждому куску слева добавляется хвост предыдущего."""
    base = _split_recursive(text, chunk_size)
    if overlap <= 0 or len(base) <= 1:
        return base

    result = [base[0]]
    for piece in base[1:]:
        tail = _overlap_tail(result[-1], overlap)
        result.append(f"{tail} {piece}".strip() if tail else piece)
    return result


def chunk_document(
    doc: ParsedDocument, chunk_size: int = 900, chunk_overlap: int = 150
) -> list[Chunk]:
    chunk_size = max(200, chunk_size)
    if chunk_overlap >= chunk_size:
        chunk_overlap = chunk_size // 4

    chunks: list[Chunk] = []

    # Накопитель одного раздела
    buffer: list[str] = []
    buffer_len = 0
    page_from: int | None = None
    page_to: int | None = None
    heading: str | None = None

    def flush() -> None:
        nonlocal buffer, buffer_len, page_from, page_to
        text = "\n".join(buffer).strip()
        buffer = []
        buffer_len = 0
        if not text:
            page_from = page_to = None
            return

        for piece in _split_with_overlap(text, chunk_size, chunk_overlap):
            if len(piece) < MIN_CHUNK_CHARS:
                continue
            chunks.append(
                Chunk(
                    index=len(chunks),
                    content=piece,
                    heading=heading,
                    page_from=page_from,
                    page_to=page_to,
                )
            )
        page_from = page_to = None

    for page in doc.pages:
        if not page.text.strip():
            continue

        if page.headings:
            flush()
            heading = page.headings[-1]

        if page_from is None:
            page_from = page.page_number
        page_to = page.page_number

        buffer.append(page.text)
        buffer_len += len(page.text)

        # Не даём буферу разрастись на всю книгу: раздел без заголовков
        # всё равно должен разрезаться, иначе теряется привязка к страницам
        if buffer_len >= chunk_size * 8:
            flush()
            page_from = page_to = page.page_number

    flush()
    return chunks
