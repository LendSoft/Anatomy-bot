from __future__ import annotations

import threading

import pytest

from app.rag import parsers


class FakePage:
    number = 0


class FakeDocument:
    def __len__(self):
        return 3

    def __getitem__(self, index: int) -> FakePage:
        return FakePage()


def test_ocr_stops_between_pages_after_cancellation(monkeypatch):
    cancel_event = threading.Event()
    processed_pages = []

    def recognize(page, languages):
        processed_pages.append(page.number)
        cancel_event.set()
        return "recognized text"

    monkeypatch.setattr(parsers, "_ocr_page", recognize)
    monkeypatch.setattr(parsers.figures_mod, "extract_page_figures", lambda *_: [])

    with pytest.raises(parsers.ParsingCancelled):
        parsers.parse_pdf_ocr(FakeDocument(), should_cancel=cancel_event.is_set)

    assert processed_pages == [0]