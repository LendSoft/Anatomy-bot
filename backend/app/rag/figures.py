"""Поиск иллюстраций внутри учебных материалов.

Задача: не собирать картинки руками, а находить их в самом файле при
индексации. Для каждой иллюстрации нужно знать три вещи:

  * где она лежит — файл и номер страницы (это уходит студенту);
  * как она подписана — «Рис. 23.1», «Figure 20.1», «Plate 8»;
  * что на ней написано — выноски с названиями структур.

Третий пункт важнее остальных. В анатомических атласах текста вне
рисунка почти нет: вся содержательная часть — подписи к линиям-выноскам
внутри изображения («Trapezius muscle», «Clavicle»). Этот текст
попадает и в поисковый индекс, и в контекст модели, поэтому бот может
разобрать рисунок словами, а не просто сослаться на него.

Разбор идёт по трём встречающимся в наших файлах случаям:

  1. Учебник: небольшие растровые картинки с подписью «Figure 23.1 ...»
     под ними. Подпись привязывается к ближайшей картинке.
  2. Атлас: страница почти целиком занята одним изображением, подписи
     структур лежат поверх него. Подпись-заголовок берётся из строки
     «Plate 8» или из колонтитула.
  3. Скан: страница — одна картинка без текстового слоя. Иллюстрацией
     считается вся страница, текст появляется только после OCR.

Предпросмотр здесь не рендерится: вырезать и сложить на диск тысячи
картинок при индексации дорого, а нужны они редко. Хранятся координаты,
а изображение вырезается из исходного файла по запросу (см.
app/services/figure_service.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.logging import get_logger

log = get_logger(__name__)

# ----------------------------------------------------------------- пороги

# Картинка меньше этого размера в точках — элемент оформления (логотип,
# иконка, линейка), а не иллюстрация
MIN_FIGURE_SIDE = 55.0
MIN_FIGURE_AREA_RATIO = 0.015

# Соседние картинки на таком расстоянии — панели одного рисунка (A, B, C).
# В учебниках Netter составной рисунок разложен на 4-6 отдельных растров
# с одной подписью на всю группу
PANEL_MERGE_GAP = 20.0

# Доля площади страницы, с которой изображение считается «страница-рисунок»
PAGE_FIGURE_RATIO = 0.45

# Насколько далеко от картинки может лежать её подпись
CAPTION_MAX_DISTANCE = 95.0

# Строка-выноска: короткая, иначе это основной текст, затёкший в границы
MAX_LABEL_LINE_CHARS = 160

# Сколько строк после «Plate 8» просматривать в поисках названия
TITLE_LOOKAHEAD_LINES = 2


# Служебные строки, которые не могут быть названием рисунка
_SERVICE_LINE = re.compile(
    r"^(?:\d+|[IVXLC]+|с\.?\s*\d+|стр\.?\s*\d+|page\s*\d+)$", re.IGNORECASE
)

# Перекрёстная ссылка под подписью: «См. также рис. 57» — это не название
_CROSS_REFERENCE = re.compile(
    r"^(?:см\.?\s*(?:также|рис)|смотри|see\s+(?:also|p|fig)|continued)", re.IGNORECASE
)

# Подпись к иллюстрации. Два алфавита: русские учебники пишут «Рис. 5.3»,
# атласы Netter — «Plate 8» и «PLATE S–48», англоязычные учебники —
# «Figure 23.1». Номер может быть составным и с буквой: «2.14а».
CAPTION_RE = re.compile(
    r"^\s*(?P<label>"
    r"(?:Рис(?:унок|\.)?|Фиг(?:ура|\.)?|Схема|Фото|Табл(?:ица|\.)?)"
    r"\s*\.?\s*\d+(?:[.\-–]\d+)*[а-яё]?"
    r"|(?:Figure|Fig\.?|Plate|Table|Chart|Exhibit)"
    r"\s*(?:[A-Z][\-–—])?\d+(?:[.\-–]\d+)*[a-z]?"
    r")\s*[.:—–)\]]?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

# Подпись к таблице — иллюстрацией не считается, но пометить полезно:
# на неё тоже ссылаются «см. таблицу 3.1»
_TABLE_LABEL = re.compile(r"^(?:Табл|Table)", re.IGNORECASE)


def _clean(text: str) -> str:
    """Убирает мягкие переносы и типографские пробелы из строки PDF."""
    text = text.replace("­", "").replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


class FigureKind:
    """Виды иллюстраций.

    Простые строки, а не enum: парсер не должен зависеть от моделей базы.
    Значения совпадают с типом figure_kind в БД, сопоставление делает
    app/services/figure_service.py.
    """

    figure = "figure"   # картинка с подписью внутри текста
    plate = "plate"     # страница-иллюстрация атласа
    table = "table"     # подпись «Таблица N»
    page = "page"       # отсканированная страница целиком


@dataclass
class ExtractedFigure:
    """Иллюстрация, найденная в документе."""

    page_number: int
    kind: str
    # Подпись как в книге: «Рис. 23.1». None — рисунок без подписи
    label: str | None = None
    # Название рисунка: текст после подписи либо колонтитул страницы
    title: str | None = None
    # Текст выносок внутри рисунка — то, что на нём написано
    labels: list[str] = field(default_factory=list)
    # Координаты в точках PDF: нужны, чтобы вырезать предпросмотр
    bbox: tuple[float, float, float, float] | None = None
    page_width: float | None = None
    page_height: float | None = None
    # Насколько уверены, что это именно иллюстрация
    confidence: float = 0.5

    @property
    def labels_text(self) -> str:
        return "; ".join(self.labels)

    def caption(self) -> str:
        """Как иллюстрация называется в одной строке."""
        parts = [p for p in (self.label, self.title) if p]
        if parts:
            return " ".join(parts) if len(parts) == 1 else f"{parts[0]} {parts[1]}"
        return {
            FigureKind.plate: "иллюстрация на всю страницу",
            FigureKind.page: "отсканированная страница",
            FigureKind.table: "таблица",
        }.get(self.kind, "рисунок без подписи")

    def index_text(self) -> str:
        """Текст, по которому иллюстрация ищется.

        Выноски идут первыми: именно по названиям структур студент и
        задаёт вопрос.
        """
        parts = [self.caption()]
        if self.labels:
            parts.append(self.labels_text)
        return "\n".join(parts)

    def to_dict(self) -> dict:
        return {
            "page_number": self.page_number,
            "kind": self.kind,
            "label": self.label,
            "title": self.title,
            "labels": self.labels,
            "bbox": list(self.bbox) if self.bbox else None,
            "page_width": self.page_width,
            "page_height": self.page_height,
            "confidence": round(self.confidence, 3),
        }


# ------------------------------------------------------- геометрия картинок


def _rects_close(a: tuple, b: tuple, gap: float = PANEL_MERGE_GAP) -> bool:
    """Пересекаются или лежат ближе gap друг к другу."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    dx = max(0.0, max(bx0 - ax1, ax0 - bx1))
    dy = max(0.0, max(by0 - ay1, ay0 - by1))
    return dx <= gap and dy <= gap


def _union(a: tuple, b: tuple) -> tuple:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _merge_panels(rects: list[tuple], gap: float = PANEL_MERGE_GAP) -> list[tuple]:
    """Склеивает панели составного рисунка в один прямоугольник.

    Повторяем проходы, пока есть что склеивать: панели A-B-C объединяются
    по цепочке, а за один проход цепочка не сойдётся.
    """
    groups = list(rects)
    changed = True
    while changed:
        changed = False
        merged: list[tuple] = []
        for rect in groups:
            for i, existing in enumerate(merged):
                if _rects_close(existing, rect, gap):
                    merged[i] = _union(existing, rect)
                    changed = True
                    break
            else:
                merged.append(rect)
        groups = merged
    return groups


def _area(rect: tuple) -> float:
    return max(0.0, rect[2] - rect[0]) * max(0.0, rect[3] - rect[1])


def _intersection_area(a: tuple, b: tuple) -> float:
    return _area(
        (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))
    )


# ------------------------------------------------------------ разбор страницы


@dataclass
class _Line:
    rect: tuple
    text: str


def _page_lines(page) -> list[_Line]:
    """Строки текста страницы вместе с координатами.

    Флаги обязательны: по умолчанию PyMuPDF вкладывает в словарь ещё и
    распакованные растры страницы. На атласе, где каждая страница —
    картинка на несколько мегабайт, это превращает 5 мс в 550 мс и
    растягивает индексацию книги с минут на часы.
    """
    import pymupdf

    lines: list[_Line] = []
    try:
        data = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)
    except Exception as exc:  # noqa: BLE001 — одна страница не должна ронять книгу
        log.warning("figure_text_failed", page=page.number + 1, error=str(exc))
        return lines

    for block in data.get("blocks", []):
        if block.get("type") != 0:  # 0 — текстовый блок
            continue
        for line in block.get("lines", []):
            text = _clean("".join(span.get("text", "") for span in line.get("spans", [])))
            if text:
                lines.append(_Line(rect=tuple(line["bbox"]), text=text))
    return lines


def _is_figure_sized(rect: tuple, page_area: float) -> bool:
    width, height = rect[2] - rect[0], rect[3] - rect[1]
    if width < MIN_FIGURE_SIDE or height < MIN_FIGURE_SIDE:
        return False
    return not (page_area and _area(rect) / page_area < MIN_FIGURE_AREA_RATIO)


def _image_rects(page, page_area: float) -> list[tuple]:
    """Прямоугольники растровых изображений, пригодных к показу."""
    rects: list[tuple] = []
    try:
        infos = page.get_image_info()
    except Exception as exc:  # noqa: BLE001
        log.warning("figure_images_failed", page=page.number + 1, error=str(exc))
        return rects

    for info in infos:
        rect = tuple(float(v) for v in info["bbox"])
        if _is_figure_sized(rect, page_area):
            rects.append(rect)
    return rects


def _drawing_rects(page, page_area: float) -> list[tuple]:
    """Прямоугольники векторных схем.

    Часть иллюстраций нарисована прямо в PDF линиями и кривыми, а не
    вставлена картинкой — такую get_image_info() не видит вовсе. Их
    приходится собирать из элементов векторной графики.

    Отбор здесь нарочно грубый — отсеиваются только мелочь и оформление.
    Главную работу делает требование подписи в extract_page_figures: по
    геометрии схему от таблицы не отличить (сетка таблицы состоит из тех
    же прямоугольников, а её текст внутри границ неотличим от выносок),
    а подпись решает вопрос однозначно.
    """
    try:
        drawings = page.get_drawings()
    except Exception as exc:  # noqa: BLE001
        log.warning("figure_drawings_failed", page=page.number + 1, error=str(exc))
        return []

    if not drawings:
        return []

    items: list[tuple] = []
    for drawing in drawings:
        rect = drawing.get("rect")
        if rect is None:
            continue
        candidate = (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))
        # Элементы-волоски: разделительные линии, подчёркивания, рамки
        if _area(candidate) <= 0:
            continue
        items.append(candidate)

    if not items:
        return []

    clusters = _merge_panels(items, gap=PANEL_MERGE_GAP)
    return [rect for rect in clusters if _is_figure_sized(rect, page_area)]


def _find_captions(lines: list[_Line]) -> list[tuple[int, _Line, str, str]]:
    """Строки-подписи: (индекс строки, строка, метка, остаток текста)."""
    found = []
    for i, line in enumerate(lines):
        match = CAPTION_RE.match(line.text)
        if match:
            found.append((i, line, _clean(match.group("label")), _clean(match.group("rest"))))
    return found


def _title_after_caption(lines: list[_Line], index: int, rest: str) -> str | None:
    """Название рисунка.

    В атласах Netter подпись и название разнесены по строкам: «Plate 8»,
    ниже — «Head and Neck: Surface Anatomy». Если после метки на той же
    строке ничего нет, смотрим следующие строки.
    """
    if rest:
        return rest

    for line in lines[index + 1 : index + 1 + TITLE_LOOKAHEAD_LINES]:
        text = line.text
        if not text or _SERVICE_LINE.match(text) or _CROSS_REFERENCE.match(text):
            continue
        if CAPTION_RE.match(text):  # сразу вторая подпись — названия нет
            break
        if len(text) <= MAX_LABEL_LINE_CHARS:
            return text
    return None


def _header_title(lines: list[_Line], page_height: float) -> str | None:
    """Колонтитул — единственная зацепка для рисунков без подписи.

    В «Атласе нейронауки» подписи «Рис. N» нет вовсе, зато сверху
    страницы стоит название раздела: «Overview of the Nervous System».
    """
    limit = page_height * 0.12
    for line in lines:
        if line.rect[1] > limit:
            break
        text = line.text
        # Номер страницы часто стоит отдельной строкой рядом с названием
        text = re.sub(r"^\d+\s*[|•]?\s*", "", text).strip()
        if len(text) < 4 or _SERVICE_LINE.match(text):
            continue
        if len(text) <= MAX_LABEL_LINE_CHARS:
            return text
    return None


def _labels_inside(rect: tuple, lines: list[_Line], used: set[int]) -> list[str]:
    """Выноски внутри рисунка.

    Строка считается выноской, если больше половины её площади попадает
    в границы изображения. Половина, а не целиком: подписи у Netter
    регулярно свисают за край растра.
    """
    labels: list[str] = []
    for i, line in enumerate(lines):
        if i in used:
            continue
        line_area = _area(line.rect)
        if line_area <= 0:
            continue
        if _intersection_area(line.rect, rect) < 0.5 * line_area:
            continue
        if len(line.text) > MAX_LABEL_LINE_CHARS:
            continue
        if _SERVICE_LINE.match(line.text):
            continue
        labels.append(line.text)
    return labels


def _caption_distance(caption_rect: tuple, figure_rect: tuple) -> float | None:
    """Расстояние от подписи до рисунка, если подпись вообще может быть его.

    Подпись почти всегда под рисунком, изредка над ним, и должна
    пересекаться с ним по горизонтали — иначе это подпись соседней
    колонки.
    """
    overlap = min(caption_rect[2], figure_rect[2]) - max(caption_rect[0], figure_rect[0])
    caption_width = caption_rect[2] - caption_rect[0]
    if caption_width > 0 and overlap < 0.25 * caption_width:
        return None

    below = caption_rect[1] - figure_rect[3]   # подпись ниже рисунка
    above = figure_rect[1] - caption_rect[3]   # подпись выше рисунка

    if -5.0 <= below <= CAPTION_MAX_DISTANCE:
        return below
    if 0.0 <= above <= CAPTION_MAX_DISTANCE * 0.6:
        # Подпись сверху встречается реже — делаем её менее приоритетной
        return above + CAPTION_MAX_DISTANCE
    # Подпись внутри рисунка (составные схемы Netter)
    if _intersection_area(caption_rect, figure_rect) > 0.5 * _area(caption_rect):
        return 0.0
    return None


def _fallback_cost(caption_rect: tuple, figure_rect: tuple) -> float:
    """Нестрогая оценка «подпись относится к этому рисунку».

    Нужна там, где вёрстка не кладёт подпись аккуратно под рисунок:
    в атласах Netter «Plate 8» стоит в нижнем углу страницы, в стороне
    от изображения, а в учебниках подпись второго рисунка бывает сдвинута
    правее его границ. Строгое правило такие случаи теряет, и рисунок
    остаётся без номера, по которому на него ссылаются в тексте.
    """
    below = caption_rect[1] - figure_rect[3]
    above = figure_rect[1] - caption_rect[3]
    if below >= -5.0:
        vertical = below
    elif above >= 0.0:
        # Подпись над рисунком — вариант возможный, но менее вероятный
        vertical = above * 1.5
    else:
        vertical = 0.0

    caption_center = (caption_rect[0] + caption_rect[2]) / 2
    figure_center = (figure_rect[0] + figure_rect[2]) / 2
    return vertical + abs(caption_center - figure_center) * 0.3


def extract_page_figures(page, page_number: int) -> list[ExtractedFigure]:
    """Иллюстрации одной страницы PDF."""
    rect = page.rect
    page_area = rect.width * rect.height
    lines = _page_lines(page)
    image_rects = _merge_panels(_image_rects(page, page_area))

    # Векторные схемы берём отдельно и только там, где их не перекрывает
    # растровая картинка: одна и та же иллюстрация часто состоит из
    # картинки и дорисованных поверх неё линий
    raster_count = len(image_rects)
    for candidate in _drawing_rects(page, page_area):
        if any(
            _intersection_area(candidate, existing) > 0.3 * _area(candidate)
            for existing in image_rects
        ):
            continue
        image_rects.append(candidate)

    if not image_rects:
        return []

    captions = _find_captions(lines)
    caption_line_indexes = {i for i, *_ in captions}

    # Каждую подпись отдаём ближайшему подходящему рисунку
    assigned: dict[int, tuple[int, _Line, str, str]] = {}
    for caption in captions:
        _, caption_line, _, _ = caption
        best_figure, best_distance = None, None
        for fig_index, figure_rect in enumerate(image_rects):
            if fig_index in assigned:
                continue
            distance = _caption_distance(caption_line.rect, figure_rect)
            if distance is None:
                continue
            if best_distance is None or distance < best_distance:
                best_figure, best_distance = fig_index, distance
        if best_figure is not None:
            assigned[best_figure] = caption

    # Второй проход — для подписей, которые не легли под рисунок строго
    fallback_limit = rect.height * 0.35
    for caption in captions:
        if caption in assigned.values():
            continue
        _, caption_line, _, _ = caption
        best_figure, best_cost = None, None
        for fig_index, figure_rect in enumerate(image_rects):
            if fig_index in assigned:
                continue
            cost = _fallback_cost(caption_line.rect, figure_rect)
            if best_cost is None or cost < best_cost:
                best_figure, best_cost = fig_index, cost
        if best_figure is not None and best_cost is not None and best_cost <= fallback_limit:
            assigned[best_figure] = caption

    header = _header_title(lines, rect.height)
    figures: list[ExtractedFigure] = []

    for fig_index, figure_rect in enumerate(image_rects):
        ratio = _area(figure_rect) / page_area if page_area else 0.0
        caption = assigned.get(fig_index)
        labels = _labels_inside(figure_rect, lines, caption_line_indexes)
        is_vector = fig_index >= raster_count

        # Векторному скоплению нужна подпись, и только она. Выноски здесь
        # ничего не доказывают: внутри границ таблицы лежит её собственный
        # текст, и по числу «выносок» таблица из трёх колонок выглядит
        # убедительнее иной схемы. Проверено на методичке, где 105 из 111
        # найденных «рисунков» оказались таблицами — все без подписей.
        # Подпись же решает вопрос однозначно: «Рис. 5.3» — схема,
        # «Таблица 3.1» — таблица, ничего — пропускаем.
        if is_vector and caption is None:
            continue

        if caption is not None:
            line_index, _, label, rest = caption
            title = _title_after_caption(lines, line_index, rest)
            kind = FigureKind.table if _TABLE_LABEL.match(label) else FigureKind.figure
            confidence = 0.95
        else:
            label, title = None, header
            kind = FigureKind.figure
            # Без подписи уверенность держится на размере и выносках
            confidence = 0.5 + (0.2 if labels else 0.0) + (0.15 if ratio >= 0.25 else 0.0)

        if ratio >= PAGE_FIGURE_RATIO and not is_vector:
            # Страница-иллюстрация: текста вокруг нет, рисунок и есть страница.
            # Для векторной схемы такой вывод неверен — «страница целиком»
            # бывает только у растра: скана или листа атласа
            kind = FigureKind.plate if (label or labels) else FigureKind.page
            confidence = max(confidence, 0.9 if labels else 0.7)

        figures.append(
            ExtractedFigure(
                page_number=page_number,
                kind=kind,
                label=label,
                title=title,
                labels=labels,
                bbox=figure_rect,
                page_width=float(rect.width),
                page_height=float(rect.height),
                confidence=min(1.0, confidence),
            )
        )

    return figures


def extract_pdf_figures(doc, page_numbers: list[int] | None = None) -> list[ExtractedFigure]:
    """Иллюстрации всего PDF. doc — открытый документ PyMuPDF."""
    figures: list[ExtractedFigure] = []
    targets = page_numbers or range(1, len(doc) + 1)

    for page_number in targets:
        try:
            figures.extend(extract_page_figures(doc[page_number - 1], page_number))
        except Exception as exc:  # noqa: BLE001
            log.warning("figure_page_failed", page=page_number, error=str(exc))

    return figures
