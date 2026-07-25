"""매칭 유스케이스.

**이 레이어는 순위를 매기지 않는다.**

규칙 필터로 후보를 좁히는 것까지가 시스템의 일이고,
순위·근거·gap 생성은 대화 중인 LLM(Claude)이 한다. 그래서 외부 LLM 비용이 0이다.

여기서 하는 일은 두 가지다.
1. 후보를 LLM 이 감당할 수 있는 크기로 좁힌다
2. 프로필 스냅샷을 함께 실어 보내 별도 조회 없이 대조하게 한다
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from core.application.profile_service import ProfileService
from core.domain.job import JobPosting
from core.domain.match import MatchCandidates, MatchFilter
from core.ports.store import JobStore

#: 출처 표기 의무가 있는 소스. API 이용 승인 조건이다.
ATTRIBUTION = {
    "saramin": "Powered by 취업 사람인 — 본 공고 정보는 사람인이 제공합니다",
}


@dataclass(frozen=True, slots=True)
class MatchContext:
    candidates: MatchCandidates
    attributions: tuple[str, ...]

    @property
    def jobs(self) -> tuple[JobPosting, ...]:
        return self.candidates.jobs


class MatchService:
    def __init__(self, profile: ProfileService, jobs: JobStore) -> None:
        self._profile = profile
        self._jobs = jobs

    async def candidates(self, flt: MatchFilter | None = None) -> MatchContext:
        criteria = flt or MatchFilter.for_newgrad_intern()
        # 마감된 공고를 후보에 넣으면 LLM 이 지원할 수 없는 것을 추천한다.
        if criteria.deadline_after is None and not criteria.include_closed:
            criteria = _with_deadline(criteria, date.today())

        postings = tuple(await self._jobs.search(criteria))
        snapshot = await self._profile.read()
        return MatchContext(
            candidates=MatchCandidates(
                profile=snapshot,
                jobs=postings,
                generated_at=datetime.now().astimezone(),
            ),
            attributions=attributions_for(postings),
        )


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
