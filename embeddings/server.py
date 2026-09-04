"""Сервис эмбеддингов и реранкера.

Вынесен в отдельный контейнер по двум причинам:
  1. Модели грузятся в память один раз, а не в каждом воркере uvicorn/arq.
  2. Крутится на CPU, чтобы не отбирать VRAM у vLLM — на карте 12-16 ГБ
     место в основном занимает сама языковая модель.

BGE-m3 выбран из-за мультиязычности: он одинаково хорошо ложится и на
русские, и на латинские анатомические термины.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Literal

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("embeddings")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
DEVICE = os.getenv("EMBEDDINGS_DEVICE", "cpu")
MAX_BATCH = int(os.getenv("EMBEDDINGS_MAX_BATCH", "64"))

app = FastAPI(title="Anatomy Bot — Embeddings & Reranker", version="1.0.0")

_state: dict[str, object] = {"embedder": None, "reranker": None, "ready": False, "error": None}
_lock = threading.Lock()


def _load_models() -> None:
    """Грузит модели в фоне, чтобы контейнер отвечал на /health сразу."""
    try:
        from sentence_transformers import CrossEncoder, SentenceTransformer

        log.info("Загрузка модели эмбеддингов %s на %s", EMBEDDING_MODEL, DEVICE)
        _state["embedder"] = SentenceTransformer(EMBEDDING_MODEL, device=DEVICE)

        log.info("Загрузка реранкера %s на %s", RERANKER_MODEL, DEVICE)
        _state["reranker"] = CrossEncoder(RERANKER_MODEL, device=DEVICE, max_length=1024)

        _state["ready"] = True
        log.info("Модели загружены, сервис готов")
    except Exception as exc:  # noqa: BLE001 — контейнер не должен падать молча
        _state["error"] = str(exc)
        log.exception("Не удалось загрузить модели")


@app.on_event("startup")
def startup() -> None:
    threading.Thread(target=_load_models, daemon=True).start()


# --------------------------------------------------------------------- схемы


class EmbedRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1)
    # Для BGE-m3 запросу и документу полезно давать разные префиксы —
    # это заметно поднимает качество на коротких вопросах.
    kind: Literal["query", "document"] = "document"
    normalize: bool = True


class EmbedResponse(BaseModel):
    vectors: list[list[float]]
    model: str
    dim: int


class RerankRequest(BaseModel):
    query: str
    documents: list[str] = Field(..., min_length=1)
    top_n: int | None = None


class RerankItem(BaseModel):
    index: int
    score: float


class RerankResponse(BaseModel):
    results: list[RerankItem]
    model: str


# ------------------------------------------------------------------- роуты


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok" if _state["ready"] else ("error" if _state["error"] else "loading"),
        "ready": _state["ready"],
        "error": _state["error"],
        "embedding_model": EMBEDDING_MODEL,
        "reranker_model": RERANKER_MODEL,
        "device": DEVICE,
    }


def _require_ready() -> None:
    if _state["error"]:
        raise HTTPException(status_code=500, detail=f"Модели не загружены: {_state['error']}")
    if not _state["ready"]:
        raise HTTPException(status_code=503, detail="Модели ещё загружаются, повторите позже")


@app.post("/embed", response_model=EmbedResponse)
def embed(req: EmbedRequest) -> EmbedResponse:
    _require_ready()
    embedder = _state["embedder"]

    texts = req.texts
    if req.kind == "query":
        texts = [f"query: {t}" for t in texts]

    # SentenceTransformer не потокобезопасен при инференсе на одной модели
    with _lock:
        vectors = embedder.encode(  # type: ignore[union-attr]
            texts,
            batch_size=MAX_BATCH,
            normalize_embeddings=req.normalize,
            show_progress_bar=False,
            convert_to_numpy=True,
        )

    vectors = np.asarray(vectors, dtype=np.float32)
    return EmbedResponse(
        vectors=vectors.tolist(),
        model=EMBEDDING_MODEL,
        dim=int(vectors.shape[1]),
    )


@app.post("/rerank", response_model=RerankResponse)
def rerank(req: RerankRequest) -> RerankResponse:
    _require_ready()
    reranker = _state["reranker"]

    pairs = [(req.query, doc) for doc in req.documents]
    with _lock:
        scores = reranker.predict(pairs, batch_size=16, show_progress_bar=False)  # type: ignore[union-attr]

    items = [RerankItem(index=i, score=float(s)) for i, s in enumerate(scores)]
    items.sort(key=lambda x: x.score, reverse=True)
    if req.top_n:
        items = items[: req.top_n]

    return RerankResponse(results=items, model=RERANKER_MODEL)
