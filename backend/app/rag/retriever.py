"""Гибридный поиск по базе учебных материалов.

Два независимых канала:
  * векторный (pgvector, косинусная близость) — понимает переформулировки
    и синонимы, но плохо различает близкие термины;
  * полнотекстовый (Postgres tsvector, русская конфигурация) — точно
    попадает в редкие и латинские названия, но не понимает смысла.

Результаты нормализуются и складываются с настраиваемым весом, затем
переранжируются кросс-энкодером. Финальная оценка сравнивается с порогом:
если лучший фрагмент ниже — пайплайн ответит отказом вместо догадки.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.rag import embeddings

log = get_logger(__name__)


@dataclass
class RetrievedChunk:
    chunk_id: int
    document_id: int
    content: str
    heading: str | None
    page_from: int | None
    page_to: int | None
    document_title: str
    document_authors: str | None
    document_section: str | None

    vector_score: float = 0.0
    text_score: float = 0.0
    hybrid_score: float = 0.0
    rerank_score: float | None = None

    @property
    def score(self) -> float:
        """Итоговая оценка: после реранка — его, иначе гибридная."""
        return self.rerank_score if self.rerank_score is not None else self.hybrid_score

    def citation(self) -> str:
        """Ссылка на источник в том виде, в каком она уйдёт студенту."""
        parts = [self.document_title]
        if self.document_authors:
            parts.append(self.document_authors)
        if self.heading:
            parts.append(self.heading)
        if self.page_from:
            pages = (
                f"с. {self.page_from}"
                if not self.page_to or self.page_to == self.page_from
                else f"с. {self.page_from}–{self.page_to}"
            )
            parts.append(pages)
        return ", ".join(parts)

    def to_log_dict(self) -> dict:
        """Сохраняется в журнал сообщений для разбора качества ответов."""
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "document_title": self.document_title,
            "heading": self.heading,
            "page_from": self.page_from,
            "page_to": self.page_to,
            "vector_score": round(self.vector_score, 4),
            "text_score": round(self.text_score, 4),
            "hybrid_score": round(self.hybrid_score, 4),
            "rerank_score": round(self.rerank_score, 4) if self.rerank_score is not None else None,
            "content": self.content[:1000],
        }


# Косинусная близость: оператор <=> у pgvector даёт расстояние, отсюда 1 - x
_VECTOR_SQL = text(
    """
    SELECT c.id, c.document_id, c.content, c.heading, c.page_from, c.page_to,
           d.title, d.authors, d.section,
           1 - (c.embedding <=> CAST(:qvec AS vector)) AS score
    FROM document_chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE c.embedding IS NOT NULL
      AND d.is_active
      AND d.status = 'ready'
      AND (CAST(:section AS varchar) IS NULL OR d.section = CAST(:section AS varchar))
    ORDER BY c.embedding <=> CAST(:qvec AS vector)
    LIMIT :limit
    """
)

# websearch_to_tsquery терпим к произвольному пользовательскому вводу —
# plainto_ и to_tsquery на вопросе с кавычками или дефисами падают
_TEXT_SQL = text(
    """
    SELECT c.id, c.document_id, c.content, c.heading, c.page_from, c.page_to,
           d.title, d.authors, d.section,
           ts_rank_cd(c.search_vector, q) AS score
    FROM document_chunks c
    JOIN documents d ON d.id = c.document_id,
         websearch_to_tsquery('russian', :query) AS q
    WHERE c.search_vector @@ q
      AND d.is_active
      AND d.status = 'ready'
      AND (CAST(:section AS varchar) IS NULL OR d.section = CAST(:section AS varchar))
    ORDER BY score DESC
    LIMIT :limit
    """
)


def _normalize(scores: dict[int, float]) -> dict[int, float]:
    """Min-max в [0, 1] — иначе ранги ts_rank_cd и косинус несопоставимы."""
    if not scores:
        return {}
    values = list(scores.values())
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return {k: 1.0 for k in scores}
    return {k: (v - lo) / (hi - lo) for k, v in scores.items()}


async def _expand_query(db: AsyncSession, query: str) -> str:
    """Дополняет запрос эквивалентами терминов из словаря ru ↔ lat.

    """
    rows = (
        await db.execute(
            text(
                """
                SELECT term_ru, term_lat, synonyms
                FROM anatomy_terms
                WHERE is_active
                  AND (:q ILIKE '%' || term_ru || '%'
                       OR (term_lat IS NOT NULL AND :q ILIKE '%' || term_lat || '%'))
                LIMIT 10
                """
            ),
            {"q": query},
        )
    ).all()

    extras: list[str] = []
    lowered = query.lower()
    for term_ru, term_lat, synonyms in rows:
        for candidate in [term_ru, term_lat, *(synonyms or [])]:
            if candidate and candidate.lower() not in lowered:
                extras.append(candidate)

    if not extras:
        return query
    log.debug("query_expanded", extras=extras[:5])
    return f"{query} {' '.join(dict.fromkeys(extras))}"


async def search(
    db: AsyncSession,
    query: str,
    *,
    top_k: int = 20,
    top_n: int = 5,
    hybrid_alpha: float = 0.6,
    use_reranker: bool = True,
    expand_query: bool = True,
    section: str | None = None,
    max_context_chars: int = 8000,
) -> list[RetrievedChunk]:
    search_query = await _expand_query(db, query) if expand_query else query

    qvec = await embeddings.embed_one(search_query, kind="query")

    vector_rows = (
        await db.execute(
            _VECTOR_SQL, {"qvec": str(qvec), "limit": top_k, "section": section}
        )
    ).all()
    text_rows = (
        await db.execute(
            _TEXT_SQL, {"query": search_query, "limit": top_k, "section": section}
        )
    ).all()

    by_id: dict[int, RetrievedChunk] = {}
    vector_scores: dict[int, float] = {}
    text_scores: dict[int, float] = {}

    for rows, scores in ((vector_rows, vector_scores), (text_rows, text_scores)):
        for row in rows:
            chunk_id = row[0]
            scores[chunk_id] = float(row[9])
            if chunk_id not in by_id:
                by_id[chunk_id] = RetrievedChunk(
                    chunk_id=chunk_id,
                    document_id=row[1],
                    content=row[2],
                    heading=row[3],
                    page_from=row[4],
                    page_to=row[5],
                    document_title=row[6],
                    document_authors=row[7],
                    document_section=row[8],
                )

    if not by_id:
        return []

    norm_vec = _normalize(vector_scores)
    norm_txt = _normalize(text_scores)

    for chunk_id, chunk in by_id.items():
        chunk.vector_score = vector_scores.get(chunk_id, 0.0)
        chunk.text_score = text_scores.get(chunk_id, 0.0)
        chunk.hybrid_score = (
            hybrid_alpha * norm_vec.get(chunk_id, 0.0)
            + (1 - hybrid_alpha) * norm_txt.get(chunk_id, 0.0)
        )

    candidates = sorted(by_id.values(), key=lambda c: c.hybrid_score, reverse=True)[:top_k]

    if use_reranker and candidates:
        ranked = await embeddings.rerank(
            query, [c.content for c in candidates], top_n=None
        )
        # Кросс-энкодер выдаёт логиты — переводим в [0, 1], чтобы порог
        # релевантности в настройках имел понятный смысл
        for idx, raw_score in ranked:
            candidates[idx].rerank_score = _sigmoid(raw_score)
        candidates.sort(key=lambda c: c.score, reverse=True)

    # Отбираем top_n, не выходя за лимит контекста
    selected: list[RetrievedChunk] = []
    used_chars = 0
    for chunk in candidates:
        if len(selected) >= top_n:
            break
        if used_chars + len(chunk.content) > max_context_chars and selected:
            continue
        selected.append(chunk)
        used_chars += len(chunk.content)

    log.debug(
        "retrieval_done",
        candidates=len(candidates),
        selected=len(selected),
        top_score=round(selected[0].score, 3) if selected else None,
    )
    return selected


def _sigmoid(x: float) -> float:
    import math

    # Ограничение аргумента спасает от переполнения на больших логитах
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))


# ---------------------------------------------------------------- иллюстрации


@dataclass
class RetrievedFigure:
    """Иллюстрация, найденная в том же материале, что и ответ."""

    figure_id: int
    document_id: int
    page_number: int
    kind: str
    label: str | None
    title: str | None
    labels: list[str]
    document_title: str
    document_authors: str | None
    confidence: float

    # Откуда взялась: рисунок на странице найденного фрагмента или
    # прямое совпадение по подписи
    source: str = "chunk_page"
    # Оценка фрагмента, на чьей странице лежит рисунок
    chunk_score: float = 0.0
    # Близость вопроса к подписи и выноскам самого рисунка
    relevance: float = 0.0
    score: float = 0.0

    def caption(self) -> str:
        parts = [p for p in (self.label, self.title) if p]
        if parts:
            return " ".join(parts)
        return {
            "plate": "иллюстрация на всю страницу",
            "page": "отсканированная страница",
            "table": "таблица",
        }.get(self.kind, "рисунок без подписи")

    def citation(self) -> str:
        """Где искать рисунок — это и есть то, что уходит студенту."""
        where = f"«{self.document_title}»"
        if self.page_number:
            where += f", с. {self.page_number}"
        return where

    def describe(self) -> str:
        """Строка для списка иллюстраций под ответом."""
        return f"{self.caption()} — {self.citation()}"

    def to_log_dict(self) -> dict:
        return {
            "figure_id": self.figure_id,
            "document_id": self.document_id,
            "document_title": self.document_title,
            "page_number": self.page_number,
            "kind": self.kind,
            "label": self.label,
            "title": self.title,
            "labels": self.labels[:40],
            "source": self.source,
            "chunk_score": round(self.chunk_score, 4),
            "relevance": round(self.relevance, 4),
            "score": round(self.score, 4),
        }


def _figure_from_row(
    row, source: str, *, chunk_score: float = 0.0, relevance: float = 0.0
) -> RetrievedFigure:
    figure = RetrievedFigure(
        figure_id=row[0],
        document_id=row[1],
        page_number=row[2],
        kind=row[3].value if hasattr(row[3], "value") else str(row[3]),
        label=row[4],
        title=row[5],
        labels=list(row[6] or []),
        document_title=row[7],
        document_authors=row[8],
        confidence=float(row[9]),
        source=source,
        chunk_score=chunk_score,
        relevance=relevance,
    )
    figure.score = _figure_score(figure)
    return figure


# Вес близости вопроса к самому рисунку в итоговой оценке. Половина на
# половину: рисунок на нужной странице, но про другое, прикладывать не
# стоит, а рисунок с подходящей подписью со случайной страницы — тем более
RELEVANCE_WEIGHT = 0.5


def _figure_score(figure: RetrievedFigure) -> float:
    """Итоговая оценка иллюстрации.

    Складывается из двух вещей: насколько релевантен фрагмент, на чьей
    странице рисунок лежит, и насколько сам рисунок (подпись и выноски)
    отвечает вопросу. Без второго слагаемого бот прикладывал бы рисунок
    к каждому ответу: в учебнике иллюстрация есть почти на каждом
    развороте, и одной близости по странице мало.
    """
    if figure.source == "figure_search":
        # Найден прямым поиском — страницы фрагмента за ним не стоит
        return figure.relevance

    if figure.relevance <= 0.0:
        # Вектора у рисунка нет (эмбеддинг не посчитан) — опираемся только
        # на фрагмент, но с запасом вниз, чтобы такие шли после остальных
        return figure.chunk_score * (1.0 - RELEVANCE_WEIGHT)

    return (
        (1.0 - RELEVANCE_WEIGHT) * figure.chunk_score
        + RELEVANCE_WEIGHT * figure.relevance
    )


_FIGURE_COLUMNS = """
    f.id, f.document_id, f.page_number, f.kind, f.label, f.title, f.labels,
    d.title, d.authors, f.confidence
"""

# Иллюстрации со страниц найденных фрагментов. Основной путь: если ответ
# собран по странице, на которой есть рисунок, студенту нужен именно он.
# Вектор вопроса здесь тоже нужен — чтобы отличить рисунок по теме ответа
# от рисунка, случайно оказавшегося на том же развороте.
_FIGURES_BY_PAGE_SQL = text(
    f"""
    SELECT {_FIGURE_COLUMNS},
           CASE
               WHEN f.embedding IS NULL THEN NULL
               ELSE 1 - (f.embedding <=> CAST(:qvec AS vector))
           END AS relevance
    FROM document_figures f
    JOIN documents d ON d.id = f.document_id
    WHERE f.is_active
      AND d.is_active
      AND f.confidence >= :min_confidence
      -- Диапазон страниц фрагмента, плюс соседняя страница: рисунок
      -- часто стоит на развороте рядом с описывающим его текстом
      AND f.document_id = :document_id
      AND f.page_number BETWEEN
          CAST(:page_from AS integer) - CAST(:page_slack AS integer)
          AND CAST(:page_to AS integer) + CAST(:page_slack AS integer)
    ORDER BY f.page_number, f.index_on_page
    LIMIT :limit
    """
)

# Прямое совпадение по подписи и выноскам — на случай, когда текст
# страницы в поиск не попал. У страницы атласа текста, кроме выносок,
# почти нет, и фрагмент по ней может не набрать веса.
_FIGURES_BY_VECTOR_SQL = text(
    f"""
    SELECT {_FIGURE_COLUMNS},
           1 - (f.embedding <=> CAST(:qvec AS vector)) AS score
    FROM document_figures f
    JOIN documents d ON d.id = f.document_id
    WHERE f.embedding IS NOT NULL
      AND f.is_active
      AND d.is_active
      AND d.status = 'ready'
      AND f.confidence >= :min_confidence
      AND (CAST(:section AS varchar) IS NULL OR d.section = CAST(:section AS varchar))
    ORDER BY f.embedding <=> CAST(:qvec AS vector)
    LIMIT :limit
    """
)


async def figures_for_chunks(
    db: AsyncSession,
    chunks: list[RetrievedChunk],
    query_vector: list[float],
    *,
    page_slack: int = 1,
    min_confidence: float = 0.5,
    per_chunk_limit: int = 6,
) -> list[RetrievedFigure]:
    """Иллюстрации, лежащие на страницах найденных фрагментов."""
    found: dict[int, RetrievedFigure] = {}
    qvec = str(query_vector)

    for chunk in chunks:
        if chunk.page_from is None:
            continue
        rows = (
            await db.execute(
                _FIGURES_BY_PAGE_SQL,
                {
                    "qvec": qvec,
                    "document_id": chunk.document_id,
                    "page_from": chunk.page_from,
                    "page_to": chunk.page_to or chunk.page_from,
                    "page_slack": page_slack,
                    "min_confidence": min_confidence,
                    "limit": per_chunk_limit,
                },
            )
        ).all()

        for row in rows:
            relevance = float(row[10]) if row[10] is not None else 0.0
            figure = _figure_from_row(
                row, source="chunk_page", chunk_score=chunk.score, relevance=relevance
            )
            # Один рисунок попадает сразу от нескольких фрагментов —
            # оставляем вариант с лучшей оценкой
            existing = found.get(figure.figure_id)
            if existing is None or figure.score > existing.score:
                found[figure.figure_id] = figure

    return sorted(found.values(), key=lambda f: f.score, reverse=True)


async def search_figures(
    db: AsyncSession,
    query_vector: list[float],
    *,
    limit: int = 10,
    min_score: float = 0.45,
    min_confidence: float = 0.5,
    section: str | None = None,
) -> list[RetrievedFigure]:
    """Поиск иллюстрации напрямую по подписи и выноскам."""
    rows = (
        await db.execute(
            _FIGURES_BY_VECTOR_SQL,
            {
                "qvec": str(query_vector),
                "limit": limit * 3,
                "section": section,
                "min_confidence": min_confidence,
            },
        )
    ).all()

    result: list[RetrievedFigure] = []
    for row in rows:
        relevance = float(row[10])
        if relevance < min_score:
            continue
        result.append(
            _figure_from_row(row, source="figure_search", relevance=relevance)
        )
        if len(result) >= limit:
            break

    return result


async def collect_figures(
    db: AsyncSession,
    query: str,
    chunks: list[RetrievedChunk],
    *,
    limit: int = 3,
    min_score: float = 0.45,
    min_confidence: float = 0.5,
    page_slack: int = 1,
    search_fallback: bool = True,
    section: str | None = None,
) -> list[RetrievedFigure]:
    """Иллюстрации к ответу: сначала со страниц ответа, потом поиском.

    Приоритет у рисунков со страниц найденных фрагментов: они заведомо
    относятся к тому, о чём написан ответ. Прямой поиск добавляется,
    только если набрать нужное число не удалось, — иначе бот начнёт
    прикладывать рисунки из других разделов, похожие лишь по подписи.

    Порог min_score применяется к обоим путям: в учебнике иллюстрация
    стоит почти на каждом развороте, и без порога бот прикладывал бы
    рисунок к любому ответу, в том числе не относящийся к вопросу.
    """
    query_vector = await embeddings.embed_one(query, kind="query")

    figures = [
        figure
        for figure in await figures_for_chunks(
            db,
            chunks,
            query_vector,
            page_slack=page_slack,
            min_confidence=min_confidence,
        )
        if figure.score >= min_score
    ]

    if len(figures) < limit and search_fallback:
        known = {figure.figure_id for figure in figures}
        extra = await search_figures(
            db,
            query_vector,
            limit=limit,
            min_score=min_score,
            min_confidence=min_confidence,
            section=section,
        )
        figures.extend(figure for figure in extra if figure.figure_id not in known)

    return figures[:limit]
