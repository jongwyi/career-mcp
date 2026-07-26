"""매칭 유스케이스.

**이 레이어는 순위를 매기지 않는다.**

규칙 필터로 후보를 좁히는 것까지가 시스템의 일이고,
순위·근거·gap 생성은 대화 중인 LLM(Claude)이 한다. 그래서 외부 LLM 비용이 0이다.

여기서 하는 일은 두 가지다.
1. 후보를 LLM 이 감당할 수 있는 크기로 좁힌다
2. 프로필 스냅샷을 함께 실어 보내 별도 조회 없이 대조하게 한다
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime

from core.application.profile_service import ProfileService
from core.domain.job import JobPosting
from core.domain.match import MatchCandidates, MatchFilter
from core.domain.job import InterestStatus, JobInterest
from core.domain.match import MatchResult, ScoredJob
from core.ports.store import InterestStore, JobStore, MatchStore

#: 출처 표기 의무가 있는 소스. API 이용 승인 조건이다.
ATTRIBUTION = {
    "saramin": "Powered by 취업 사람인 — 본 공고 정보는 사람인이 제공합니다",
}


@dataclass(frozen=True, slots=True)
class MatchContext:
    candidates: MatchCandidates
    attributions: tuple[str, ...]
    #: 공고별 지난번 점수. 같은 공고를 다시 볼 때 비교 기준이 된다.
    previous_scores: Mapping[int, MatchResult] = field(default_factory=dict)
    dismissed_count: int = 0

    @property
    def jobs(self) -> tuple[JobPosting, ...]:
        return self.candidates.jobs


class MatchService:
    def __init__(
        self,
        profile: ProfileService,
        jobs: JobStore,
        interest: InterestStore | None = None,
        history: MatchStore | None = None,
    ) -> None:
        self._profile = profile
        self._jobs = jobs
        self._interest = interest
        self._history = history

    async def candidates(self, flt: MatchFilter | None = None) -> MatchContext:
        criteria = flt or MatchFilter.for_newgrad_intern()
        # 마감된 공고를 후보에 넣으면 LLM 이 지원할 수 없는 것을 추천한다.
        if criteria.deadline_after is None and not criteria.include_closed:
            criteria = _with_deadline(criteria, date.today())

        dismissed = list(await self._interest.dismissed_ids()) if self._interest else []
        postings = tuple(await self._jobs.search(criteria, exclude_ids=dismissed))
        snapshot = await self._profile.read()

        previous: Mapping[int, MatchResult] = {}
        if self._history and postings:
            previous = await self._history.latest_scores(
                [p.id for p in postings if p.id is not None]
            )

        return MatchContext(
            candidates=MatchCandidates(
                profile=snapshot,
                jobs=postings,
                generated_at=datetime.now().astimezone(),
            ),
            attributions=attributions_for(postings),
            previous_scores=previous,
            dismissed_count=len(dismissed),
        )

    async def save_scores(
        self, scores: Sequence[ScoredJob], *, criteria: MatchFilter
    ) -> int:
        """LLM 이 매긴 점수를 남긴다.

        매번 새로 판단하므로 기록이 없으면 어제 80점이 오늘 65점이어도 알 수 없다.
        """
        if self._history is None:
            raise RuntimeError("MatchStore 가 연결되지 않았다")
        snapshot = await self._profile.read()
        return await self._history.save_results(
            scores, criteria=criteria, fact_count=snapshot.fact_count
        )

    async def mark(
        self, job_id: int, status: InterestStatus, *, note: str | None = None
    ) -> JobInterest:
        if self._interest is None:
            raise RuntimeError("InterestStore 가 연결되지 않았다")
        return await self._interest.mark(job_id, status, note=note)

    async def marked(
        self, statuses: Sequence[InterestStatus] = ()
    ) -> Sequence[JobInterest]:
        if self._interest is None:
            return []
        return await self._interest.list_by_status(statuses)


    async def restricted_count(self, flt: MatchFilter) -> int:
        """기본 조회에서 빠진 제한 공고가 몇 건인지.

        조용히 빼면 사용자는 "공고가 없다"로 이해한다. 항상 같이 보고한다.
        """
        from dataclasses import replace

        target = replace(flt, include_restricted=True)
        total = await self._jobs.count(target)
        unrestricted = await self._jobs.count(replace(flt, include_restricted=False))
        return max(total - unrestricted, 0)


def attributions_for(postings: tuple[JobPosting, ...]) -> tuple[str, ...]:
    sources = {p.key.source_id for p in postings}
    return tuple(ATTRIBUTION[s] for s in sorted(sources) if s in ATTRIBUTION)


def _with_deadline(flt: MatchFilter, value: date) -> MatchFilter:
    from dataclasses import replace

    return replace(flt, deadline_after=value)
