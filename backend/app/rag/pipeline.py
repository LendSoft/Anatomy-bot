"""Ответ на вопрос студента: поиск → проверка порога → генерация.

Один и тот же путь используют VK-бот, проверка из админки и прогон
контрольных наборов — иначе результаты тестирования не отражали бы то,
что видит студент.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.llm.base import ChatMessage, GenerationParams, LLMError
from app.llm.factory import get_fallback_llm, get_llm
from app.models.prompt import Prompt, PromptKind
from app.rag import prompts as P
from app.rag import retriever
from app.rag.retriever import RetrievedChunk, RetrievedFigure
from app.services import settings_service

log = get_logger(__name__)

# Точное совпадение после нормализации — иначе вопрос «Привет, а что такое
# гайморова пазуха?» тоже попал бы под приветствие вместо поиска по базе
GREETING_TRIGGERS = frozenset({
    "привет", "здравствуйте", "здравствуй", "добрый день", "добрый вечер",
    "доброе утро", "приветствую", "хай", "начать", "start", "/start",
    "помощь", "/помощь", "help", "/help",
})


def _is_greeting(question: str) -> bool:
    return question.strip().lower().rstrip("!.,") in GREETING_TRIGGERS


@dataclass
class AnswerResult:
    answer: str
    refused: bool
    chunks: list[RetrievedChunk] = field(default_factory=list)
    # Иллюстрации, найденные в тех же материалах, что и ответ
    figures: list[RetrievedFigure] = field(default_factory=list)
    top_score: float | None = None

    llm_provider: str | None = None
    llm_model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    prompt_version: int | None = None

    retrieval_ms: int = 0
    generation_ms: int = 0
    total_ms: int = 0

    generation_params: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


async def _load_prompt(db: AsyncSession, kind: PromptKind) -> Prompt | None:
    return (
        await db.execute(
            select(Prompt).where(Prompt.kind == kind, Prompt.is_active.is_(True))
        )
    ).scalar_one_or_none()


def _build_messages(
    system_prompt: str,
    examples: list[dict] | None,
    history: list[tuple[str, str]],
    user_message: str,
) -> list[ChatMessage]:
    messages = [ChatMessage(role="system", content=system_prompt)]

    # Эталонные ответы идут как пары реплик: модель перенимает и структуру
    # ответа, и привычку отказываться, когда данных нет
    for example in examples or []:
        question = example.get("question")
        answer = example.get("answer")
        if question and answer:
            messages.append(ChatMessage(role="user", content=question))
            messages.append(ChatMessage(role="assistant", content=answer))

    for prev_question, prev_answer in history:
        messages.append(ChatMessage(role="user", content=prev_question))
        messages.append(ChatMessage(role="assistant", content=prev_answer))

    messages.append(ChatMessage(role="user", content=user_message))
    return messages


async def answer_question(
    db: AsyncSession,
    question: str,
    *,
    history: list[tuple[str, str]] | None = None,
    section: str | None = None,
    overrides: dict[str, Any] | None = None,
    include_sources: bool = True,
    include_figures: bool = True,
) -> AnswerResult:
    """Формирует ответ на вопрос.

    overrides позволяет прогнать вопрос на других параметрах, не меняя
    сохранённые настройки — этим пользуется проверка из админки.
    """
    started = time.monotonic()
    cfg = await settings_service.get_all(db)
    if overrides:
        cfg.update({k: v for k, v in overrides.items() if v is not None})

    result = AnswerResult(answer="", refused=False)

    # ------------------------------------------------------ приветствие
    if bool(cfg["greeting_enabled"]) and _is_greeting(question):
        result.answer = str(cfg["greeting_message"])
        result.total_ms = int((time.monotonic() - started) * 1000)
        return result

    # -------------------------------------------------------------- поиск
    retrieval_started = time.monotonic()
    try:
        chunks = await retriever.search(
            db,
            question,
            top_k=int(cfg["retrieval_top_k"]),
            top_n=int(cfg["rerank_top_n"]),
            hybrid_alpha=float(cfg["hybrid_alpha"]),
            use_reranker=bool(cfg["use_reranker"]),
            expand_query=bool(cfg["expand_query_with_glossary"]),
            section=section,
            max_context_chars=int(cfg["max_context_chars"]),
        )
    except Exception as exc:  # noqa: BLE001 — сбой поиска не должен ронять бота
        log.exception("retrieval_failed")
        result.error = f"Ошибка поиска: {exc}"
        result.answer = (
            "Не удалось выполнить поиск по базе материалов. Попробуйте повторить запрос позже."
        )
        result.total_ms = int((time.monotonic() - started) * 1000)
        return result

    result.retrieval_ms = int((time.monotonic() - retrieval_started) * 1000)
    result.chunks = chunks
    result.top_score = chunks[0].score if chunks else None

    # ---------------------------------------------- порог достоверности
    min_score = float(cfg["min_relevance_score"])
    if not chunks or (result.top_score or 0.0) < min_score:
        log.info(
            "answer_refused_by_threshold",
            top_score=result.top_score,
            threshold=min_score,
            question=question[:120],
        )
        result.refused = True
        result.answer = P.REFUSAL_MESSAGE
        result.total_ms = int((time.monotonic() - started) * 1000)
        return result

    # ------------------------------------------------------- иллюстрации
    # Рисунки подбираются до генерации, а не после: модель должна описать,
    # что на них обозначено, и сослаться на страницу. Если искать их
    # после, в ответе о рисунках не будет ни слова.
    if include_figures and cfg["figures_enabled"]:
        try:
            result.figures = await retriever.collect_figures(
                db,
                question,
                chunks,
                limit=int(cfg["figures_max_count"]),
                min_score=float(cfg["figures_min_score"]),
                min_confidence=float(cfg["figures_min_confidence"]),
                page_slack=int(cfg["figures_page_slack"]),
                search_fallback=bool(cfg["figures_search_fallback"]),
                section=section,
            )
        except Exception as exc:  # noqa: BLE001 — рисунок необязателен, текст ответа важнее
            log.warning("figure_search_failed", error=str(exc))

    # ---------------------------------------------------------- генерация
    system_prompt_row = await _load_prompt(db, PromptKind.system)
    examples_row = await _load_prompt(db, PromptKind.reference_answers)

    system_prompt = system_prompt_row.content if system_prompt_row else P.DEFAULT_SYSTEM_PROMPT
    examples = examples_row.examples if examples_row else P.DEFAULT_REFERENCE_ANSWERS
    result.prompt_version = system_prompt_row.version if system_prompt_row else None

    history_turns = int(cfg["history_turns"])
    trimmed_history = (history or [])[-history_turns:] if history_turns > 0 else []

    user_message = P.build_user_message(
        question, chunks, style=str(cfg["answer_style"]), figures=result.figures
    )
    messages = _build_messages(system_prompt, examples, trimmed_history, user_message)

    params = GenerationParams(
        temperature=float(cfg["temperature"]),
        top_p=float(cfg["top_p"]),
        max_tokens=int(cfg["max_tokens"]),
    )
    result.generation_params = {
        **params.as_dict(),
        "retrieval_top_k": int(cfg["retrieval_top_k"]),
        "rerank_top_n": int(cfg["rerank_top_n"]),
        "hybrid_alpha": float(cfg["hybrid_alpha"]),
        "min_relevance_score": min_score,
        "use_reranker": bool(cfg["use_reranker"]),
    }

    # Настройки из панели важнее переменных окружения: их правят без
    # перезапуска контейнера
    provider = settings_service.resolve(cfg, "llm_provider_override")
    model = settings_service.resolve(cfg, "llm_model_override")
    gigachat_key = settings_service.resolve(cfg, "gigachat_auth_key")
    gigachat_scope = settings_service.resolve(cfg, "gigachat_scope")
    gigachat_model = settings_service.resolve(cfg, "gigachat_model")

    llm = get_llm(
        provider=provider,
        model=gigachat_model if provider == "gigachat" and not model else model,
        api_key=gigachat_key if provider == "gigachat" else None,
        scope=gigachat_scope if provider == "gigachat" else None,
    )

    generation_started = time.monotonic()
    try:
        response = await llm.chat(messages, params)
    except LLMError as primary_error:
        fallback = (
            get_fallback_llm(
                api_key=gigachat_key, model=gigachat_model, scope=gigachat_scope
            )
            if cfg["fallback_on_error"]
            else None
        )
        if fallback is None:
            log.error("llm_failed_no_fallback", error=str(primary_error))
            result.error = str(primary_error)
            result.answer = (
                "Сервис генерации ответов временно недоступен. Попробуйте позже."
            )
            result.total_ms = int((time.monotonic() - started) * 1000)
            return result

        log.warning("llm_fallback_used", error=str(primary_error))
        try:
            response = await fallback.chat(messages, params)
        except LLMError as fallback_error:
            log.error("llm_fallback_failed", error=str(fallback_error))
            result.error = f"{primary_error}; резервный провайдер: {fallback_error}"
            result.answer = (
                "Сервис генерации ответов временно недоступен. Попробуйте позже."
            )
            result.total_ms = int((time.monotonic() - started) * 1000)
            return result

    result.generation_ms = int((time.monotonic() - generation_started) * 1000)
    result.llm_provider = response.provider
    result.llm_model = response.model
    result.prompt_tokens = response.prompt_tokens
    result.completion_tokens = response.completion_tokens

    answer = (response.content or "").strip()

    # Модель сообщила, что данных не хватает — отдаём человеческую формулировку
    if P.REFUSAL_MARKER in answer:
        log.info("answer_refused_by_model", question=question[:120])
        result.refused = True
        result.answer = P.REFUSAL_MESSAGE
        result.total_ms = int((time.monotonic() - started) * 1000)
        return result

    if not answer:
        result.error = "Модель вернула пустой ответ"
        result.answer = P.REFUSAL_MESSAGE
        result.refused = True
        result.total_ms = int((time.monotonic() - started) * 1000)
        return result

    # Точные координаты рисунка дописываем сами: номер страницы — то, по
    # чему студент пойдёт искать изображение, и опечатка модели здесь
    # дороже лишней строки под ответом
    if result.figures:
        answer = f"{answer}\n\n{P.format_figures(result.figures)}"

    if include_sources:
        answer = f"{answer}\n\n{P.format_sources(chunks)}"

    result.answer = answer
    result.total_ms = int((time.monotonic() - started) * 1000)
    return result
