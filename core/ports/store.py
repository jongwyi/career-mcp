"""저장소 포트. 인터페이스만 두고 구현은 adapters/store 에 있다.

application 레이어는 이 파일만 알면 된다. Supabase 의 존재를 몰라야 한다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol

from core.domain.job import JobPosting, JobKey, RawPosting, SourceStatus
from core.domain.match import MatchFilter, MatchResult
from core.domain.profile import (
    AttributeKey,
    DiscardReason,
    Fact,
    FactKind,
    FactSource,
    ProfileAttributes,
    ProfileSnapshot,
)


class ProfileStore(Protocol):
    async def add_fact(self, fact: Fact) -> Fact:
        """저장하고 id 가 채워진 Fact 를 돌려준다."""
        ...

    async def get_fact(self, fact_id: int) -> Fact | None: ...

    async def list_facts(
        self,
        *,
        kinds: Sequence[FactKind] | None = None,
        active_only: bool = True,
        since: datetime | None = None,
        source: FactSource | None = None,
    ) -> Sequence[Fact]:
        """since/source 조합이 profile_diff 를 지탱한다."""
        ...

    async def supersede_fact(self, fact_id: int, replacement: Fact) -> Fact:
        """replacement 를 저장하고 원본에 superseded_by 를 건다. 원자적이어야 한다."""
        ...

    async def discard_fact(
        self, fact_id: int, *, reason: DiscardReason
    ) -> Fact:
        """사실을 비활성화한다. 지우지 않는다.

        임포트한 JSON 에 다른 사람의 정보나 틀린 내용이 섞일 수 있다.
        되돌아보거나 되살릴 수 있어야 하므로 삭제하지 않는다.
        """
        ...

    async def restore_fact(self, fact_id: int) -> Fact:
        """보류를 취소한다."""
        ...

    async def list_discarded(self) -> Sequence[Fact]: ...

    async def get_attributes(self) -> ProfileAttributes: ...

    async def set_attribute(self, key: AttributeKey, value: str) -> None: ...

    async def load_snapshot(self) -> ProfileSnapshot | None:
        """캐시된 스냅샷. 없으면 None — 호출측이 facts 로 재생성한다."""
        ...

    async def save_snapshot(self, snapshot: ProfileSnapshot) -> None: ...


class RawStore(Protocol):
    """모든 수집 경로의 공통 착지점.

    배치 메서드가 있는 이유는 규모 때문이다. 공고 1건당 왕복 3회를 하면
    1만 건 수집에 3만 요청이 들고 40분이 걸린다 — GH Actions 제한을 넘는다.
    단건 메서드는 크롬 확장처럼 한두 건씩 들어오는 경로용으로 남긴다.
    """

    async def append(self, raw: RawPosting) -> RawPosting: ...

    async def append_many(self, raws: Sequence[RawPosting]) -> Sequence[RawPosting]: ...

    async def list_unparsed(self, *, limit: int = 100) -> Sequence[RawPosting]:
        """파서를 고친 뒤 재처리할 대상."""
        ...

    async def mark_parsed(
        self, raw_id: int, *, ok: bool, reason: str | None = None
    ) -> None: ...

    async def mark_parsed_many(
        self, raw_ids: Sequence[int], *, ok: bool, reason: str | None = None
    ) -> None: ...

    async def prune(self, *, batch_limit: int = 2000) -> int:
        """공고당 최신 1건만 남기고 오래된 원본을 한 배치 지운다.

        전체 백필마다 원본이 누적되면 무료 한도를 넘긴다.
        전체를 한 문장에 지우면 타임아웃이 나므로 배치로 나눈다 —
        호출측이 0 이 될 때까지 반복한다.
        """
        ...


class JobStore(Protocol):
    async def upsert(self, posting: JobPosting) -> JobPosting:
        """(source_id, external_id) 기준 upsert. last_seen 을 갱신한다."""
        ...

    async def upsert_many(
        self, postings: Sequence[JobPosting]
    ) -> Sequence[JobPosting]: ...

    async def get(self, job_id: int) -> JobPosting | None: ...

    async def search(self, flt: MatchFilter) -> Sequence[JobPosting]:
        """① 규칙 필터 단계. 수백 건을 flt.limit 건까지 좁힌다."""
        ...

    async def count(self, flt: MatchFilter) -> int:
        """limit 과 무관한 전체 건수. 제외된 공고를 보고하는 데 쓴다."""
        ...

    async def mark_closed(self, keys: Sequence[JobKey]) -> int:
        """마감 공고는 삭제하지 않는다. 놓친 기회 회고가 가능해야 한다."""
        ...

    async def ingest_status(self) -> Mapping[str, SourceStatus]: ...


class MatchStore(Protocol):
    async def save_results(
        self, results: Sequence[MatchResult], *, criteria: MatchFilter
    ) -> int:
        """run_id 를 돌려준다."""
        ...

    async def history(self, job_id: int) -> Sequence[MatchResult]: ...
