"""공고 조회 유스케이스."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from core.domain.job import JobPosting, SourceStatus
from core.domain.match import MatchFilter, MatchResult
from core.ports.store import JobStore, MatchStore


class JobQueryService:
    def __init__(self, jobs: JobStore, history: MatchStore | None = None) -> None:
        self._jobs = jobs
        self._history = history

    async def match_history(
        self, *, job_id: int | None = None, limit: int = 30
    ) -> Sequence[MatchResult]:
        if self._history is None:
            return []
        return await self._history.history(job_id=job_id, limit=limit)

    async def search(self, flt: MatchFilter) -> Sequence[JobPosting]:
        return await self._jobs.search(flt)

    async def detail(self, job_id: int) -> JobPosting | None:
        return await self._jobs.get(job_id)

    async def status(self) -> Mapping[str, SourceStatus]:
        return await self._jobs.ingest_status()

    async def close_expired(self, today: date | None = None) -> int:
        close = getattr(self._jobs, "close_expired", None)
        if close is None:
            return 0
        return await close(today)
