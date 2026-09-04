"""Тесты нарезки учебного текста.

Проверяем то, от чего напрямую зависит качество поиска: склейку переносов
по слогам, соблюдение размера фрагмента, привязку к страницам и разделам.
"""

from __future__ import annotations

from app.rag.chunking import chunk_document
from app.rag.parsers import PageText, ParsedDocument, clean_text, detect_headings

LONG_TEXT = (
    "Наружная сонная артерия отдаёт передние, задние и медиальные ветви, "
    "кровоснабжающие органы головы и шеи. "
)


def make_doc(pages: list[tuple[int, str]]) -> ParsedDocument:
    return ParsedDocument(
        pages=[
            PageText(page_number=number, text=text, headings=detect_headings(text))
            for number, text in pages
        ]
    )


def test_hyphen_break_is_joined():
    """В учебниках слова разорваны переносом — без склейки они не найдутся."""
    raw = "является одной из ко-\nнечных ветвей общей сонной артерии"
    assert "конечных" in clean_text(raw)


def test_chunks_respect_size_limit():
    doc = make_doc([(1, LONG_TEXT * 40)])
    chunks = chunk_document(doc, chunk_size=800, chunk_overlap=100)

    assert chunks
    # Перекрытие добавляется слева, поэтому допуск на его размер
    assert all(len(c.content) <= 800 + 100 + 20 for c in chunks)


def test_chunk_indexes_are_unique_and_sequential():
    doc = make_doc([(1, LONG_TEXT * 30), (2, LONG_TEXT * 30)])
    chunks = chunk_document(doc, chunk_size=600, chunk_overlap=80)

    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_heading_switch_closes_previous_chunk():
    """Фрагмент не должен смешивать материал двух разделов."""
    doc = make_doc(
        [
            (1, "АРТЕРИИ ГОЛОВЫ\n" + LONG_TEXT * 5),
            (2, "ВЕНЫ ШЕИ\n" + LONG_TEXT * 5),
        ]
    )
    chunks = chunk_document(doc, chunk_size=900, chunk_overlap=100)

    headings = {c.heading for c in chunks}
    assert "АРТЕРИИ ГОЛОВЫ" in headings
    assert "ВЕНЫ ШЕИ" in headings
    # Ни один фрагмент не относится сразу к двум разделам
    assert all(c.heading in ("АРТЕРИИ ГОЛОВЫ", "ВЕНЫ ШЕИ") for c in chunks)


def test_pages_are_tracked():
    doc = make_doc([(10, LONG_TEXT * 20), (11, LONG_TEXT * 20)])
    chunks = chunk_document(doc, chunk_size=900, chunk_overlap=100)

    assert chunks[0].page_from == 10
    assert all(c.page_from is not None for c in chunks)


def test_empty_pages_are_skipped():
    doc = make_doc([(1, ""), (2, "   "), (3, LONG_TEXT * 10)])
    chunks = chunk_document(doc, chunk_size=700, chunk_overlap=50)

    assert chunks
    assert all(c.page_from == 3 for c in chunks)


def test_short_fragments_are_dropped():
    """Обрывки в пару слов только зашумляют поиск."""
    doc = make_doc([(1, "Ага.")])
    assert chunk_document(doc, chunk_size=900, chunk_overlap=100) == []


def test_overlap_disabled():
    doc = make_doc([(1, LONG_TEXT * 20)])
    chunks = chunk_document(doc, chunk_size=500, chunk_overlap=0)

    assert chunks
    assert all(len(c.content) <= 520 for c in chunks)


def test_overlap_larger_than_chunk_is_clamped():
    """Некорректная настройка не должна приводить к зацикливанию."""
    doc = make_doc([(1, LONG_TEXT * 20)])
    chunks = chunk_document(doc, chunk_size=400, chunk_overlap=900)

    assert chunks
