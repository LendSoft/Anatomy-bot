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
      AND (:section IS NULL OR d.section = :section)
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
      AND (:section IS NULL OR d.section = :section)
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


async def search_images(
    db: AsyncSession,
    query: str,
    *,
    limit: int = 2,
    min_score: float = 0.45,
    section: str | None = None,
) -> list[dict]:
    """Подбор иллюстраций из атласов к ответу."""
    qvec = await embeddings.embed_one(query, kind="query")

    rows = (
        await db.execute(
            text(
                """
                SELECT id, title, description, stored_path, thumbnail_path,
                       source_title, source_page, vk_attachment_id,
                       1 - (embedding <=> CAST(:qvec AS vector)) AS score
                FROM atlas_images
                WHERE embedding IS NOT NULL
                  AND is_active
                  AND (:section IS NULL OR section = :section)
                ORDER BY embedding <=> CAST(:qvec AS vector)
                LIMIT :limit
                """
            ),
            {"qvec": str(qvec), "limit": limit * 3, "section": section},
        )
    ).all()

    result = []
    for row in rows:
        score = float(row[8])
        if score < min_score:
            continue
        result.append(
            {
                "image_id": row[0],
                "title": row[1],
                "description": row[2],
                "stored_path": row[3],
                "thumbnail_path": row[4],
                "source_title": row[5],
                "source_page": row[6],
                "vk_attachment_id": row[7],
                "score": round(score, 4),
            }
        )
        if len(result) >= limit:
            break

    return result
