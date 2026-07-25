"""매칭 도메인. 외부 의존성 없음.

중요: 이 레이어는 순위를 매기지 않는다.
후보를 좁히는 것까지가 시스템의 일이고, 순위·근거·gap 생성은
대화 중인 LLM(Claude 또는 GPT)이 한다. 그래서 v1 에 외부 LLM 비용이 없다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from core.domain.job import CareerLevel, EmploymentType, JobPosting
from core.domain.profile import ProfileSnapshot

# LLM 리랭크에 넘길 후보 수. 너무 많으면 컨텍스트를 낭비하고,
# 너무 적으면 규칙 필터의 오차를 LLM 이 교정할 여지가 없다.
DEFAULT_CANDIDATE_LIMIT = 40


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class MatchFilter:
    """① 규칙 필터 단계의 입력. SQL 로 번역된다."""

    keyword: str | None = None
    employment_types: tuple[EmploymentType, ...] = ()
    career_levels: tuple[CareerLevel, ...] = ()
    location: str | None = None
    deadline_after: date | None = None
    include_closed: bool = False
    limit: int = DEFAULT_CANDIDATE_LIMIT

    def __post_init__(self) -> None:
        if self.limit <= 0:
            raise ValueError("limit 은 1 이상이어야 한다")

    @classmethod
    def for_newgrad_intern(cls, **kwargs: object) -> MatchFilter:
        """가장 흔한 조회. 인턴 + 신입이 지원 가능한 것.

        career_level 이 unknown 인 공고도 포함한다 — 소스가 값을 안 준 것이지
        신입을 안 받는다는 뜻이 아니다. 누락이 오분류보다 비싸다.
        """
        return cls(
            employment_types=(EmploymentType.INTERN,),
            career_levels=(
                CareerLevel.NEWGRAD,
                CareerLevel.BOTH,
                CareerLevel.UNKNOWN,
            ),
            **kwargs,  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class Evidence:
    """근거 없는 매칭 점수는 신뢰할 수 없다.

    fact_id 로 프로필 Fact 를 역참조해 "왜 맞다고 보는지"를 추적한다.
    """

    jd_requirement: str
    fact_id: int


@dataclass(frozen=True, slots=True)
class Gap:
    """부족한 요건. 이게 '약점 보완' 목표로 이어지는 연결점이다."""

    jd_requirement: str
    severity: Severity
    suggestion: str


@dataclass(frozen=True, slots=True)
class MatchCandidates:
    """jobs_match 가 반환하는 것. 순위가 없다.

    프로필 스냅샷을 함께 실어 보내 LLM 이 별도 조회 없이 대조할 수 있게 한다.
    """

    profile: ProfileSnapshot
    jobs: tuple[JobPosting, ...]
    generated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MatchResult:
    """LLM 이 만들어 되돌려주는 판정. match_results 에 저장해 gap 변화를 추적한다."""

    job_id: int
    score: int
    matched: tuple[Evidence, ...] = ()
    gaps: tuple[Gap, ...] = ()

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 100:
            raise ValueError(f"score 는 0~100 범위여야 한다: {self.score}")
