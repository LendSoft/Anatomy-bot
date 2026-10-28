"""Тесты поиска иллюстраций внутри документов.

Проверяется то, от чего зависит, сможет ли бот сослаться на рисунок:
разбор подписи, склейка панелей составного рисунка, сбор выносок внутри
изображения и привязка подписи к картинке.

PDF для тестов собирается здесь же средствами PyMuPDF: это позволяет
задать точную геометрию (где картинка, где подпись, где выноски) и не
тащить в репозиторий многомегабайтные учебники.

Подписи в собранных PDF — латиницей. Встроенные шрифты PDF (base-14
Helvetica) кириллицу не кодируют: вставленный текст извлекается обратно
набором «ЇЇЇ», и проверять по нему разбор нельзя. Русские форматы
подписей целиком покрыты тестами самого выражения CAPTION_RE ниже —
геометрия разбора от языка подписи не зависит.
"""

from __future__ import annotations

import pymupdf
import pytest

from app.rag.figures import (
    CAPTION_RE,
    FigureKind,
    _merge_panels,
    extract_page_figures,
)


def _png_bytes(width: int = 200, height: int = 150) -> bytes:
    """Простейшая картинка — содержимое не важно, важны границы."""
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height))
    pixmap.set_rect(pixmap.irect, (200, 120, 90))
    return pixmap.tobytes("png")


def _page(
    images: list[tuple] = (),
    texts: list[tuple] = (),
    shapes: list[tuple] = (),
    table_rows: list[tuple] = (),
):
    """Страница A4 с картинками, текстом и векторной графикой.

    images:     (x0, y0, x1, y1) — растровая картинка
    texts:      (x, y, строка)
    shapes:     (x0, y0, x1, y1) — фигура нарисованной схемы
    table_rows: (x0, y0, x1, y1) — строка таблицы во всю её ширину
    """
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)

    for rect in images:
        # keep_proportion=False — иначе картинка впишется в прямоугольник
        # по своим пропорциям и окажется не там, где её ждёт тест
        page.insert_image(pymupdf.Rect(*rect), stream=_png_bytes(), keep_proportion=False)
    for rect in shapes:
        page.draw_oval(pymupdf.Rect(*rect), color=(0, 0, 0), width=1)
    for rect in table_rows:
        page.draw_rect(pymupdf.Rect(*rect), color=(0, 0, 0), width=0.5)
    for x, y, text in texts:
        page.insert_text((x, y), text, fontsize=9)

    # Перечитываем документ: вставленные объекты попадают в структуру
    # страницы только после сохранения
    reopened = pymupdf.open("pdf", doc.tobytes())
    doc.close()
    return reopened


# --------------------------------------------------------------- подписи


@pytest.mark.parametrize(
    ("line", "label"),
    [
        ("Рис. 5.3 Плечевая кость", "Рис. 5.3"),
        ("Рисунок 12 Строение сердца", "Рисунок 12"),
        ("Figure 23.1  Structure of the anal sphincter", "Figure 23.1"),
        ("FIG 1.3 Formation of the heart loop.", "FIG 1.3"),
        ("Plate 202 Topography of Lungs", "Plate 202"),
        ("PLATE S–48 Arteries of Brain", "PLATE S–48"),
        ("Таблица 3.1 Классификация мышц", "Таблица 3.1"),
        ("Рис. 2.14а Вид сбоку", "Рис. 2.14а"),
    ],
)
def test_caption_formats_are_recognized(line: str, label: str):
    """Подписи в наших учебниках оформлены по-разному — ловим все варианты."""
    match = CAPTION_RE.match(line)
    assert match is not None, line
    assert match.group("label").strip() == label


@pytest.mark.parametrize(
    "line",
    [
        "Наружная сонная артерия отдаёт четыре группы ветвей",
        "Рисунок показывает строение сердца",  # без номера — не подпись
        "В таблице приведены данные",
        "123",
    ],
)
def test_plain_text_is_not_a_caption(line: str):
    assert CAPTION_RE.match(line) is None


# ---------------------------------------------------- склейка панелей


def test_adjacent_panels_merge_into_one_figure():
    """Составной рисунок в учебнике разложен на отдельные растры.

    Четыре панели с одной подписью должны стать одним рисунком, иначе
    бот сошлётся на один и тот же рисунок четыре раза.
    """
    panels = [
        (50, 100, 150, 200),
        (160, 100, 260, 200),
        (50, 205, 150, 305),
        (160, 205, 260, 305),
    ]
    merged = _merge_panels(panels)

    assert len(merged) == 1
    assert merged[0] == (50, 100, 260, 305)


def test_distant_images_stay_separate():
    """Две картинки в разных частях страницы — два разных рисунка."""
    merged = _merge_panels([(50, 100, 200, 200), (50, 600, 200, 700)])
    assert len(merged) == 2


# ------------------------------------------------------- разбор страницы


def test_caption_below_image_is_attached():
    page = _page(
        images=[(100, 100, 400, 400)],
        texts=[(100, 420, "Figure 5.3 Humerus, posterior view")],
    )
    figures = extract_page_figures(page[0], 42)

    assert len(figures) == 1
    figure = figures[0]
    assert figure.label == "Figure 5.3"
    assert figure.title == "Humerus, posterior view"
    assert figure.page_number == 42
    assert figure.kind == FigureKind.figure
    # Подпись найдена — разбор надёжный
    assert figure.confidence >= 0.9
    page.close()


def test_labels_inside_image_are_collected():
    """Выноски внутри рисунка — главное содержимое страницы атласа.

    Именно по ним бот рассказывает, что на изображении обозначено.
    """
    page = _page(
        images=[(100, 100, 450, 500)],
        texts=[
            (150, 150, "Trapezius muscle"),
            (150, 200, "Clavicle"),
            (150, 250, "Brachial plexus"),
            # Вне границ рисунка — это основной текст, не выноска
            (100, 700, "Neck muscles are divided into superficial and deep."),
        ],
    )
    figures = extract_page_figures(page[0], 7)

    assert len(figures) == 1
    labels = figures[0].labels
    assert "Trapezius muscle" in labels
    assert "Clavicle" in labels
    assert "Brachial plexus" in labels
    assert not any("Neck muscles" in label for label in labels)
    page.close()


def test_caption_at_page_bottom_still_attaches():
    """В атласах «Plate 8» стоит в нижнем углу, далеко от изображения.

    Строгое правило «подпись под рисунком» такой случай теряет, и
    рисунок остаётся без номера, по которому на него ссылаются в тексте.
    """
    page = _page(
        images=[(70, 140, 520, 600)],
        texts=[
            (200, 300, "Infraorbital margin"),
            (480, 780, "Plate 8"),
            (200, 795, "Head and Neck: Surface Anatomy"),
        ],
    )
    figures = extract_page_figures(page[0], 63)

    assert len(figures) == 1
    assert figures[0].label == "Plate 8"
    page.close()


def test_full_page_image_without_text_is_a_scan():
    """Страница скана — одна картинка без текстового слоя."""
    page = _page(images=[(0, 0, 595, 842)])
    figures = extract_page_figures(page[0], 301)

    assert len(figures) == 1
    assert figures[0].kind == FigureKind.page
    page.close()


def test_full_page_image_with_labels_is_a_plate():
    """Страница атласа: картинка на всю страницу плюс выноски поверх."""
    page = _page(
        images=[(30, 30, 565, 700)],
        texts=[(100, 100, "Clavicle"), (100, 150, "Sternoclavicular joint")],
    )
    figures = extract_page_figures(page[0], 55)

    assert len(figures) == 1
    assert figures[0].kind == FigureKind.plate
    assert len(figures[0].labels) == 2
    page.close()


def test_decorative_images_are_ignored():
    """Логотип или иконка в колонтитуле — не иллюстрация."""
    page = _page(images=[(20, 20, 60, 50)])
    assert extract_page_figures(page[0], 1) == []
    page.close()


def test_page_without_images_yields_nothing():
    """Страница с одним текстом и таблицами рисунков не содержит."""
    page = _page(texts=[(50, 100, "Содержимое некоторых сообщений полости рта")])
    assert extract_page_figures(page[0], 41) == []
    page.close()


def test_two_figures_get_their_own_captions():
    """Две картинки на странице не должны делить одну подпись."""
    page = _page(
        images=[(100, 80, 350, 250), (100, 400, 350, 570)],
        texts=[
            (100, 270, "Figure 23.1 Structure of the anal sphincter"),
            (100, 590, "Figure 23.2 Anal manometry"),
        ],
    )
    figures = extract_page_figures(page[0], 56)

    assert len(figures) == 2
    labels = sorted(figure.label for figure in figures)
    assert labels == ["Figure 23.1", "Figure 23.2"]
    page.close()


def test_table_caption_marks_table_kind():
    page = _page(
        images=[(100, 100, 400, 300)],
        texts=[(100, 320, "Table 3.1 Classification of muscles")],
    )
    figures = extract_page_figures(page[0], 12)

    assert len(figures) == 1
    assert figures[0].kind == FigureKind.table
    page.close()


def test_caption_without_title_takes_following_line():
    """«Plate 10», а название — строкой ниже."""
    page = _page(
        images=[(100, 100, 400, 350)],
        texts=[
            (100, 370, "Plate 10"),
            (100, 385, "Superficial Arteries and Veins of Face"),
        ],
    )
    figures = extract_page_figures(page[0], 65)

    assert figures[0].label == "Plate 10"
    assert figures[0].title == "Superficial Arteries and Veins of Face"
    page.close()


def test_cross_reference_is_not_used_as_title():
    """«See also Plates 57, 83» — перекрёстная ссылка, а не название."""
    page = _page(
        images=[(100, 100, 400, 350)],
        texts=[
            (100, 370, "Plate 10"),
            (100, 385, "See also Plates 57, 83, 84"),
            (100, 400, "Superficial Arteries of Face"),
        ],
    )
    figures = extract_page_figures(page[0], 65)

    assert figures[0].title == "Superficial Arteries of Face"
    page.close()


# ------------------------------------------------- векторные схемы и таблицы


def test_vector_figure_with_caption_is_found():
    """Схема, нарисованная в PDF линиями, а не вставленная картинкой.

    Такую get_image_info() не видит вовсе, и без разбора векторной
    графики рисунок потерялся бы целиком.
    """
    page = _page(
        shapes=[(100, 100, 250, 200), (260, 100, 410, 200), (100, 210, 250, 310)],
        texts=[
            (120, 150, "Aorta"),
            (100, 340, "Figure 7.2 Scheme of blood circulation"),
        ],
    )
    figures = extract_page_figures(page[0], 88)

    assert len(figures) == 1
    assert figures[0].label == "Figure 7.2"
    assert figures[0].title == "Scheme of blood circulation"
    page.close()


def test_table_grid_without_caption_is_not_a_figure():
    """Таблица — не иллюстрация, и ссылаться на неё как на рисунок нельзя.

    Сетка таблицы состоит из тех же прямоугольников, что и схема, а
    текст внутри её границ по формальным признакам не отличим от
    выносок. В методичке из базы такие таблицы занимают страницы
    целиком — без этой проверки бот отправлял бы студента «смотреть
    рисунок» на страницу с текстовой таблицей.
    """
    rows = [(80, 80 + index * 40, 530, 115 + index * 40) for index in range(8)]
    page = _page(
        table_rows=rows,
        texts=[
            (90, 100, "Name"),
            (250, 100, "Location"),
            (400, 100, "Function"),
            (90, 140, "Lateral spinothalamic tract"),
            (250, 140, "Anterior part of lateral funiculus"),
            (400, 140, "Pain and temperature"),
        ],
    )
    assert extract_page_figures(page[0], 151) == []
    page.close()


def test_captioned_table_keeps_table_kind():
    """Подписанная таблица записывается таблицей, а не рисунком.

    Вид определяет подпись: по геометрии сетка таблицы и схема в PDF
    устроены одинаково. Благодаря этому бот может сослаться на
    «таблицу 3.1», не выдавая её за изображение.
    """
    page = _page(
        table_rows=[(80, 80 + index * 40, 530, 115 + index * 40) for index in range(6)],
        texts=[
            (90, 100, "Name"),
            (250, 100, "Function"),
            (80, 340, "Table 3.1 Classification of conducting tracts"),
        ],
    )
    figures = extract_page_figures(page[0], 151)

    assert len(figures) == 1
    assert figures[0].kind == FigureKind.table
    page.close()


def test_vector_shapes_under_raster_are_not_duplicated():
    """Поверх картинки часто дорисованы линии-выноски.

    Это одна иллюстрация, а не две: иначе бот сошлётся на один рисунок
    дважды.
    """
    page = _page(
        images=[(100, 100, 450, 450)],
        shapes=[(150, 150, 300, 300)],
        texts=[(100, 470, "Figure 9.1 Heart chambers")],
    )
    figures = extract_page_figures(page[0], 120)

    assert len(figures) == 1
    page.close()


# ------------------------------------------------------- вывод для ответа


def test_index_text_puts_labels_after_caption():
    """По index_text рисунок ищется — выноски обязаны в него попадать."""
    page = _page(
        images=[(100, 100, 450, 500)],
        texts=[
            (150, 150, "Clavicle"),
            (100, 520, "Figure 5.3 Humerus"),
        ],
    )
    figure = extract_page_figures(page[0], 42)[0]
    text = figure.index_text()

    assert "Figure 5.3" in text
    assert "Humerus" in text
    assert "Clavicle" in text
    page.close()


def test_caption_falls_back_when_nothing_recognized():
    """Без подписи и выносок рисунок всё равно должен как-то называться."""
    page = _page(images=[(100, 100, 300, 300)])
    figure = extract_page_figures(page[0], 5)[0]

    assert figure.caption()
    assert figure.label is None
    page.close()
