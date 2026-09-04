"""Агрегаты для дашборда админ-панели."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def overview(db: AsyncSession, days: int = 30) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days)

    totals = (
        await db.execute(
            text(
                """
                SELECT
                    count(*) FILTER (WHERE role = 'assistant')                       AS answers,
                    count(*) FILTER (WHERE status = 'answered')                      AS answered,
                    count(*) FILTER (WHERE status = 'refused')                       AS refused,
                    count(*) FILTER (WHERE status = 'error')                         AS errors,
                    count(*) FILTER (WHERE status = 'rate_limited')                  AS limited,
                    avg(total_ms) FILTER (WHERE status = 'answered')                 AS avg_ms,
                    percentile_cont(0.95) WITHIN GROUP (ORDER BY total_ms)
                        FILTER (WHERE status = 'answered')                           AS p95_ms,
                    avg(top_score) FILTER (WHERE status = 'answered')                AS avg_top_score,
                    sum(coalesce(prompt_tokens, 0) + coalesce(completion_tokens, 0)) AS tokens
                FROM messages
                WHERE created_at >= :since
                """
            ),
            {"since": since},
        )
    ).mappings().one()

    library = (
        await db.execute(
            text(
                """
                SELECT
                    count(*)                                        AS documents,
                    count(*) FILTER (WHERE status = 'ready')        AS documents_ready,
                    count(*) FILTER (WHERE status = 'failed')       AS documents_failed,
                    coalesce(sum(chunks_count), 0)                  AS chunks,
                    coalesce(sum(pages_count), 0)                   AS pages
                FROM documents
                """
            )
        )
    ).mappings().one()

    images = (
        await db.execute(
            text(
                "SELECT count(*) AS total, "
                "count(*) FILTER (WHERE embedding IS NOT NULL) AS indexed "
                "FROM atlas_images"
            )
        )
    ).mappings().one()

    users = (
        await db.execute(
            text(
                """
                SELECT count(*) AS total,
                       count(*) FILTER (WHERE last_seen_at >= :since) AS active
                FROM vk_users
                """
            ),
            {"since": since},
        )
    ).mappings().one()

    answers = totals["answers"] or 0
    return {
        "period_days": days,
        "questions": answers,
        "answered": totals["answered"] or 0,
        "refused": totals["refused"] or 0,
        "errors": totals["errors"] or 0,
        "rate_limited": totals["limited"] or 0,
        "refusal_rate": round((totals["refused"] or 0) / answers, 4) if answers else 0.0,
        "avg_latency_ms": round(totals["avg_ms"] or 0),
        "p95_latency_ms": round(totals["p95_ms"] or 0),
        "avg_top_score": round(float(totals["avg_top_score"] or 0), 4),
        "tokens_used": int(totals["tokens"] or 0),
        "documents": library["documents"],
        "documents_ready": library["documents_ready"],
        "documents_failed": library["documents_failed"],
        "chunks": library["chunks"],
        "pages": library["pages"],
        "images_total": images["total"],
        "images_indexed": images["indexed"],
        "vk_users_total": users["total"],
        "vk_users_active": users["active"],
    }


async def daily(db: AsyncSession, days: int = 30) -> list[dict[str, Any]]:
    """Ряд по дням. generate_series даёт нули за дни без запросов —
    иначе на графике образуются разрывы.

    Приведение типов только через CAST: postgres-синтаксис `:since::date`
    ломает разбор параметров в SQLAlchemy — двоеточия принимаются за часть
    имени параметра, и запрос уходит в базу неподставленным.
    """
    since = datetime.now(UTC) - timedelta(days=days)

    rows = (
        await db.execute(
            text(
                """
                SELECT CAST(d AS date)                                    AS day,
                       count(m.id) FILTER (WHERE m.status = 'answered')   AS answered,
                       count(m.id) FILTER (WHERE m.status = 'refused')    AS refused,
                       count(m.id) FILTER (WHERE m.status = 'error')      AS errors,
                       coalesce(round(avg(m.total_ms)
                           FILTER (WHERE m.status = 'answered')), 0)      AS avg_ms
                FROM generate_series(CAST(:since AS date), current_date, '1 day') AS d
                LEFT JOIN messages m
                       ON m.created_at >= d
                      AND m.created_at < d + interval '1 day'
                      AND m.role = 'assistant'
                GROUP BY d
                ORDER BY d
                """
            ),
            {"since": since},
        )
    ).mappings().all()

    return [
        {
            "date": row["day"].isoformat(),
            "answered": row["answered"],
            "refused": row["refused"],
            "errors": row["errors"],
            "avg_latency_ms": int(row["avg_ms"]),
        }
        for row in rows
    ]


async def top_questions(db: AsyncSession, days: int = 30, limit: int = 20) -> list[dict]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = (
        await db.execute(
            text(
                """
                SELECT lower(trim(content)) AS question, count(*) AS count
                FROM messages
                WHERE role = 'user' AND created_at >= :since
                GROUP BY 1
                HAVING count(*) > 1
                ORDER BY count DESC
                LIMIT :limit
                """
            ),
            {"since": since, "limit": limit},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def unanswered(db: AsyncSession, days: int = 30, limit: int = 50) -> list[dict]:
    """Вопросы, на которые бот отказался отвечать.

    Самый практичный отчёт: показывает, каких материалов не хватает в базе.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    rows = (
        await db.execute(
            text(
                """
                SELECT q.content AS question,
                       a.created_at,
                       a.top_score
                FROM messages a
                JOIN LATERAL (
                    SELECT content
                    FROM messages u
                    WHERE u.conversation_id = a.conversation_id
                      AND u.role = 'user'
                      AND u.created_at <= a.created_at
                    ORDER BY u.created_at DESC
                    LIMIT 1
                ) q ON true
                WHERE a.status = 'refused' AND a.created_at >= :since
                ORDER BY a.created_at DESC
                LIMIT :limit
                """
            ),
            {"since": since, "limit": limit},
        )
    ).mappings().all()

    return [
        {
            "question": row["question"],
            "created_at": row["created_at"].isoformat(),
            "top_score": float(row["top_score"]) if row["top_score"] is not None else None,
        }
        for row in rows
    ]
