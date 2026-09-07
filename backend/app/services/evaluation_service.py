"""Прогон контрольных наборов вопросов.

Соответствует разделу 9 ТЗ: проверяем, находит ли бот нужный материал,
соответствует ли ответ учебнику и не добавляет ли отсебятины. Оценку
ставит LLM-судья, преподаватель может её перекрыть вручную.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.llm.base import ChatMessage, GenerationParams, LLMError
from app.llm.factory import get_llm
from app.models.evaluation import RunStatus, TestQuestion, TestResult, TestRun
from app.models.prompt import Prompt, PromptKind
from app.rag import pipeline
from app.rag import prompts as P
from app.services import settings_service

log = get_logger(__name__)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


async def _judge_prompt(db: AsyncSession) -> str:
    row = (
        await db.execute(
            select(Prompt).where(
                Prompt.kind == PromptKind.judge, Prompt.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    return row.content if row else P.DEFAULT_JUDGE_PROMPT


async def judge_answer(
    db: AsyncSession, question: str, reference: str | None, answer: str
) -> tuple[float | None, str | None]:
    """Оценка ответа судьёй. Возвращает (оценка, комментарий)."""
    if not reference:
        # Без эталона сравнивать не с чем — оценку ставит преподаватель
        return None, "Эталонный ответ не задан, оценка вручную"

    system_prompt = await _judge_prompt(db)
    user_message = (
        f"ВОПРОС ПОЛЬЗОВАТЕЛЯ:\n{question}\n\n"
        f"ЭТАЛОННЫЙ ОТВЕТ:\n{reference}\n\n"
        f"ОТВЕТ БОТА:\n{answer}"
    )

    llm = get_llm()
    try:
        response = await llm.chat(
            [
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=user_message),
            ],
            # Судья должен быть воспроизводим, отсюда нулевая температура
            GenerationParams(temperature=0.0, top_p=1.0, max_tokens=512),
        )
    except LLMError as exc:
        log.warning("judge_failed", error=str(exc))
        return None, f"Судья недоступен: {exc}"

    match = _JSON_BLOCK.search(response.content or "")
    if not match:
        return None, "Судья вернул ответ не в формате JSON"

    try:
        verdict = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None, "Не удалось разобрать ответ судьи"

    score = verdict.get("score")
    comment = str(verdict.get("comment", "")).strip()
    if verdict.get("has_hallucination"):
        comment = f"⚠ Обнаружены сведения вне эталона. {comment}"

    try:
        return float(score), comment or None
    except (TypeError, ValueError):
        return None, comment or "Судья не вернул числовую оценку"


async def run_test_set(
    db: AsyncSession, run_id: int, *, overrides: dict[str, Any] | None = None
) -> None:
    """Прогоняет весь набор. Вызывается из воркера."""
    run = (await db.execute(select(TestRun).where(TestRun.id == run_id))).scalar_one_or_none()
    if run is None:
        return

    questions = (
        await db.execute(
            select(TestQuestion)
            .where(TestQuestion.test_set_id == run.test_set_id)
            .order_by(TestQuestion.id)
        )
    ).scalars().all()

    cfg = await settings_service.get_all(db, use_cache=False)
    if overrides:
        cfg.update(overrides)

    run.status = RunStatus.running
    run.started_at = datetime.now(UTC)
    run.total_questions = len(questions)
    run.completed_questions = 0
    run.settings_snapshot = cfg
    run.llm_model = str(cfg.get("llm_model_override") or "")
    await db.commit()

    scores: list[float] = []
    latencies: list[int] = []
    refusals = 0

    try:
        for question in questions:
            try:
                result = await pipeline.answer_question(
                    db,
                    question.question,
                    overrides=overrides,
                    include_sources=False,
                    include_images=False,
                )
            except Exception as exc:  # noqa: BLE001 — один вопрос не должен рушить прогон
                log.exception("test_question_failed", question_id=question.id)
                db.add(
                    TestResult(
                        run_id=run.id, question_id=question.id, error_message=str(exc)[:1000]
                    )
                )
                run.completed_questions += 1
                await db.commit()
                continue

            if result.refused:
                refusals += 1

            # Вопросы «бот должен отказаться» оцениваем по факту отказа,
            # а не сравнением текста: правильный отказ — это пятёрка
            if question.should_refuse:
                score: float | None = 5.0 if result.refused else 1.0
                comment = (
                    "Корректный отказ на вопрос вне базы"
                    if result.refused
                    else "Бот ответил на вопрос, на который должен был отказаться"
                )
            elif result.refused:
                score = 1.0
                comment = "Бот отказался отвечать на вопрос, который есть в программе"
            else:
                score, comment = await judge_answer(
                    db, question.question, question.reference_answer, result.answer
                )

            if score is not None:
                scores.append(score)
            latencies.append(result.total_ms)

            db.add(
                TestResult(
                    run_id=run.id,
                    question_id=question.id,
                    answer=result.answer,
                    refused=result.refused,
                    retrieved_chunks=[c.to_log_dict() for c in result.chunks],
                    top_score=result.top_score,
                    latency_ms=result.total_ms,
                    judge_score=score,
                    judge_comment=comment,
                    error_message=result.error,
                )
            )
            run.completed_questions += 1
            await db.commit()

        run.status = RunStatus.completed
        run.avg_score = sum(scores) / len(scores) if scores else None
        run.refusal_rate = refusals / len(questions) if questions else None
        run.avg_latency_ms = sum(latencies) / len(latencies) if latencies else None
        run.finished_at = datetime.now(UTC)
        await db.commit()

        log.info(
            "test_run_completed",
            run_id=run.id,
            avg_score=run.avg_score,
            refusal_rate=run.refusal_rate,
        )

    except Exception as exc:  # noqa: BLE001
        log.exception("test_run_failed", run_id=run_id)
        await db.rollback()
        await db.execute(
            update(TestRun)
            .where(TestRun.id == run_id)
            .values(
                status=RunStatus.failed,
                error_message=str(exc)[:2000],
                finished_at=datetime.now(UTC),
            )
        )
        await db.commit()
