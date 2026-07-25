"""공고 조회 유스케이스."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from core.domain.job import JobPosting, SourceStatus
from core.domain.match import MatchFilter
from core.ports.store import JobStore


class JobQueryService:
    def __init__(self, jobs: JobStore) -> None:
        self._jobs = jobs

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
