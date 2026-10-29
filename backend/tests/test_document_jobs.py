from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.worker import queue


class FakePool:
    def __init__(self):
        self.queued = [b"queued-match", b"queued-other"]
        self.active = [b"arq:in-progress:active-match"]

    async def zrange(self, key: str, start: int, end: int) -> list[bytes]:
        return self.queued

    async def keys(self, pattern: str) -> list[bytes]:
        return self.active


class FakeJob:
    infos = {
        "queued-match": SimpleNamespace(function="index_document", args=(7,)),
        "queued-other": SimpleNamespace(function="index_document", args=(8,)),
        "active-match": SimpleNamespace(function="embed_figures", args=(7,)),
    }
    aborted: list[str] = []

    def __init__(self, job_id: str, pool: FakePool):
        self.job_id = job_id

    async def info(self):
        return self.infos.get(self.job_id)

    async def abort(self, *, timeout: float):
        self.aborted.append(self.job_id)
        return True


@pytest.mark.asyncio
async def test_document_jobs_match_only_the_requested_document(monkeypatch):
    pool = FakePool()

    async def fake_get_pool():
        return pool

    monkeypatch.setattr(queue, "get_pool", fake_get_pool)
    monkeypatch.setattr(queue, "Job", FakeJob)

    jobs = await queue.document_jobs(7)

    assert {job.job_id for job in jobs} == {"queued-match", "active-match"}


@pytest.mark.asyncio
async def test_abort_document_jobs_only_aborts_matching_jobs(monkeypatch):
    FakeJob.aborted = []
    pool = FakePool()

    async def fake_get_pool():
        return pool

    monkeypatch.setattr(queue, "get_pool", fake_get_pool)
    monkeypatch.setattr(queue, "Job", FakeJob)

    aborted = await queue.abort_document_jobs(7)

    assert aborted == 2
    assert set(FakeJob.aborted) == {"queued-match", "active-match"}