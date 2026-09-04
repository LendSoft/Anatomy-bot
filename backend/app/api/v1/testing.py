"""Контрольные наборы вопросов и прогоны тестирования."""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select

from app.api.deps import CurrentAdmin, DbSession
from app.models.evaluation import (
    RunStatus,
    TestQuestion,
    TestResult,
    TestRun,
    TestSet,
)
from app.schemas.chat import (
    ManualScoreRequest,
    TestQuestionCreate,
    TestQuestionOut,
    TestResultOut,
    TestRunCreate,
    TestRunOut,
    TestSetCreate,
    TestSetOut,
)
from app.schemas.common import MessageResponse, Page
from app.worker.queue import enqueue

router = APIRouter(prefix="/testing", tags=["Тестирование"])


# ------------------------------------------------------------------ наборы


@router.get("/sets", response_model=list[TestSetOut])
async def list_sets(db: DbSession, _: CurrentAdmin) -> list[TestSetOut]:
    rows = (
        await db.execute(
            select(TestSet, func.count(TestQuestion.id))
            .outerjoin(TestQuestion, TestQuestion.test_set_id == TestSet.id)
            .group_by(TestSet.id)
            .order_by(TestSet.created_at.desc())
        )
    ).all()

    items = []
    for test_set, questions_count in rows:
        item = TestSetOut.model_validate(test_set)
        item.questions_count = questions_count
        items.append(item)
    return items


@router.post("/sets", response_model=TestSetOut, status_code=status.HTTP_201_CREATED)
async def create_set(payload: TestSetCreate, db: DbSession, _: CurrentAdmin) -> TestSetOut:
    test_set = TestSet(**payload.model_dump())
    db.add(test_set)
    await db.commit()
    await db.refresh(test_set)
    return TestSetOut.model_validate(test_set)


@router.delete("/sets/{set_id}", response_model=MessageResponse)
async def delete_set(set_id: int, db: DbSession, _: CurrentAdmin) -> MessageResponse:
    test_set = await db.get(TestSet, set_id)
    if test_set is None:
        raise HTTPException(status_code=404, detail="Набор не найден")
    await db.delete(test_set)
    await db.commit()
    return MessageResponse(detail="Набор удалён")


# ----------------------------------------------------------------- вопросы


@router.get("/sets/{set_id}/questions", response_model=list[TestQuestionOut])
async def list_questions(set_id: int, db: DbSession, _: CurrentAdmin) -> list[TestQuestion]:
    return list(
        (
            await db.execute(
                select(TestQuestion)
                .where(TestQuestion.test_set_id == set_id)
                .order_by(TestQuestion.id)
            )
        ).scalars().all()
    )


@router.post(
    "/sets/{set_id}/questions",
    response_model=TestQuestionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_question(
    set_id: int, payload: TestQuestionCreate, db: DbSession, _: CurrentAdmin
) -> TestQuestion:
    if await db.get(TestSet, set_id) is None:
        raise HTTPException(status_code=404, detail="Набор не найден")

    question = TestQuestion(test_set_id=set_id, **payload.model_dump())
    db.add(question)
    await db.commit()
    await db.refresh(question)
    return question


@router.post("/sets/{set_id}/questions/import", response_model=MessageResponse)
async def import_questions(
    set_id: int, db: DbSession, _: CurrentAdmin, file: UploadFile = File(...)
) -> MessageResponse:
    """Импорт из CSV.

    Колонки: question, reference_answer, expected_source, should_refuse.
    Преподавателям удобнее готовить контрольные вопросы в таблице, чем
    вбивать их по одному в форму.
    """
    if await db.get(TestSet, set_id) is None:
        raise HTTPException(status_code=404, detail="Набор не найден")

    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    # Excel в русской локали сохраняет CSV с точкой с запятой
    dialect = csv.Sniffer().sniff(raw[:2048], delimiters=",;\t") if raw.strip() else csv.excel
    reader = csv.DictReader(io.StringIO(raw), dialect=dialect)

    if not reader.fieldnames or "question" not in reader.fieldnames:
        raise HTTPException(
            status_code=400, detail="В файле должна быть колонка «question»"
        )

    added = 0
    for row in reader:
        question_text = (row.get("question") or "").strip()
        if not question_text:
            continue
        db.add(
            TestQuestion(
                test_set_id=set_id,
                question=question_text,
                reference_answer=(row.get("reference_answer") or "").strip() or None,
                expected_source=(row.get("expected_source") or "").strip() or None,
                should_refuse=str(row.get("should_refuse", "")).strip().lower()
                in ("1", "true", "да", "yes"),
            )
        )
        added += 1

    await db.commit()
    return MessageResponse(detail=f"Добавлено вопросов: {added}")


@router.delete("/questions/{question_id}", response_model=MessageResponse)
async def delete_question(question_id: int, db: DbSession, _: CurrentAdmin) -> MessageResponse:
    question = await db.get(TestQuestion, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Вопрос не найден")
    await db.delete(question)
    await db.commit()
    return MessageResponse(detail="Вопрос удалён")


# ----------------------------------------------------------------- прогоны


@router.get("/runs", response_model=Page[TestRunOut])
async def list_runs(
    db: DbSession,
    _: CurrentAdmin,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    test_set_id: int | None = None,
) -> Page[TestRunOut]:
    query = select(TestRun)
    count_query = select(func.count(TestRun.id))
    if test_set_id:
        query = query.where(TestRun.test_set_id == test_set_id)
        count_query = count_query.where(TestRun.test_set_id == test_set_id)

    total = (await db.execute(count_query)).scalar_one()
    rows = (
        await db.execute(
            query.order_by(TestRun.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    ).scalars().all()

    return Page[TestRunOut](
        items=[TestRunOut.model_validate(row) for row in rows],
        total=total,
        page=page,
        size=size,
    )


@router.post("/runs", response_model=TestRunOut, status_code=status.HTTP_201_CREATED)
async def start_run(payload: TestRunCreate, db: DbSession, _: CurrentAdmin) -> TestRun:
    test_set = await db.get(TestSet, payload.test_set_id)
    if test_set is None:
        raise HTTPException(status_code=404, detail="Набор не найден")

    questions_count = (
        await db.execute(
            select(func.count(TestQuestion.id)).where(
                TestQuestion.test_set_id == payload.test_set_id
            )
        )
    ).scalar_one()
    if not questions_count:
        raise HTTPException(status_code=400, detail="В наборе нет вопросов")

    run = TestRun(
        test_set_id=payload.test_set_id,
        name=payload.name or f"Прогон набора «{test_set.name}»",
        status=RunStatus.pending,
        total_questions=questions_count,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    await enqueue("run_test_set", run.id, payload.overrides)
    return run


@router.get("/runs/{run_id}", response_model=TestRunOut)
async def get_run(run_id: int, db: DbSession, _: CurrentAdmin) -> TestRun:
    run = await db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Прогон не найден")
    return run


@router.get("/runs/{run_id}/results", response_model=list[TestResultOut])
async def get_run_results(run_id: int, db: DbSession, _: CurrentAdmin) -> list[TestResultOut]:
    rows = (
        await db.execute(
            select(TestResult, TestQuestion)
            .join(TestQuestion, TestQuestion.id == TestResult.question_id)
            .where(TestResult.run_id == run_id)
            .order_by(TestResult.id)
        )
    ).all()

    items = []
    for result, question in rows:
        item = TestResultOut.model_validate(result)
        item.question = question.question
        item.reference_answer = question.reference_answer
        items.append(item)
    return items


@router.post("/results/{result_id}/score", response_model=TestResultOut)
async def set_manual_score(
    result_id: int, payload: ManualScoreRequest, db: DbSession, _: CurrentAdmin
) -> TestResultOut:
    """Оценка преподавателя. Перекрывает оценку судьи."""
    result = await db.get(TestResult, result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Результат не найден")

    result.manual_score = payload.manual_score
    result.manual_comment = payload.manual_comment
    await db.commit()
    await db.refresh(result)
    return TestResultOut.model_validate(result)


@router.delete("/runs/{run_id}", response_model=MessageResponse)
async def delete_run(run_id: int, db: DbSession, _: CurrentAdmin) -> MessageResponse:
    run = await db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Прогон не найден")
    await db.delete(run)
    await db.commit()
    return MessageResponse(detail="Прогон удалён")
