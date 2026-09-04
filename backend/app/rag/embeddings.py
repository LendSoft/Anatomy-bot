"""Клиент сервиса эмбеддингов и реранкера."""

from __future__ import annotations

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=settings.embeddings_base_url,
            # Пакетная индексация учебника на CPU идёт долго
            timeout=httpx.Timeout(300.0, connect=10.0),
        )
    return _client


class EmbeddingsError(RuntimeError):
    pass


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.ConnectError, httpx.ReadTimeout)),
    reraise=True,
)
async def embed(texts: list[str], kind: str = "document") -> list[list[float]]:
    """Векторы для списка текстов. kind: query | document."""
    if not texts:
        return []
    try:
        resp = await _get_client().post("/embed", json={"texts": texts, "kind": kind})
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise EmbeddingsError(
            f"Сервис эмбеддингов вернул {exc.response.status_code}: {exc.response.text[:300]}"
        ) from exc
    except httpx.HTTPError as exc:
        raise EmbeddingsError(f"Сервис эмбеддингов недоступен: {exc}") from exc

    return resp.json()["vectors"]


async def embed_one(text: str, kind: str = "query") -> list[float]:
    return (await embed([text], kind=kind))[0]


async def rerank(query: str, documents: list[str], top_n: int | None = None) -> list[tuple[int, float]]:
    """Возвращает пары (индекс документа, оценка), отсортированные по убыванию."""
    if not documents:
        return []
    try:
        resp = await _get_client().post(
            "/rerank", json={"query": query, "documents": documents, "top_n": top_n}
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        # Реранкер не критичен: при сбое отдаём исходный порядок,
        # ответ студенту важнее идеального ранжирования
        log.warning("rerank_failed", error=str(exc))
        return [(i, 0.0) for i in range(len(documents))]

    return [(item["index"], item["score"]) for item in resp.json()["results"]]


async def wait_ready(timeout: float = 900.0, interval: float = 10.0) -> bool:
    """Ждёт, пока сервис догрузит модели.

    При первом запуске это занимает несколько минут: скачиваются веса
    bge-m3 и реранкера. Без ожидания первый же загруженный документ
    уходил бы в ошибку просто потому, что не успел прогреться сервис.
    """
    import asyncio
    import time

    deadline = time.monotonic() + timeout
    notified = False

    while time.monotonic() < deadline:
        state = await health()
        if state.get("ready"):
            return True
        if state.get("error"):
            log.error("embeddings_failed_to_load", error=state["error"])
            return False
        if not notified:
            log.info("waiting_for_embeddings", timeout_seconds=timeout)
            notified = True
        await asyncio.sleep(interval)

    return False


async def health() -> dict:
    try:
        resp = await _get_client().get("/health", timeout=10.0)
        return resp.json()
    except httpx.HTTPError as exc:
        return {"status": "error", "ready": False, "error": str(exc)}


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
