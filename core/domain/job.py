"""채용 공고 도메인. 외부 의존성 없음.

수집 경로는 셋(공식 API / 워커 스크랩 / 크롬 확장)이지만
정규화 경로는 하나다. 모든 입력은 RawPosting 을 거쳐 JobPosting 이 된다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any

# 확장이 보내는 HTML 스냅샷 상한. 이걸 넘으면 잘라서 보관한다.
MAX_HTML_SNAPSHOT = 200_000


class EmploymentType(StrEnum):
    """고용형태. '어떤 신분으로 일하는가'."""

    INTERN = "intern"        # 청년인턴 (체험형/채용형 포함)
    FULLTIME = "fulltime"    # 정규직
    CONTRACT = "contract"    # 계약직 / 비정규직 / 무기계약직
    UNKNOWN = "unknown"


class CareerLevel(StrEnum):
    """채용구분. '누구를 뽑는가'.

    고용형태와 직교하는 축이다. 하나로 합치면 '정규직 신입'과 '계약직 신입'이
    구분되지 않고, 실제 소스(재정경제부 API, 사람인)도 둘을 별개 필드로 준다.
    """

    NEWGRAD = "newgrad"          # 신입
    EXPERIENCED = "experienced"  # 경력
    BOTH = "both"                # 신입+경력 (신입도 지원 가능)
    UNKNOWN = "unknown"

    @property
    def open_to_newgrad(self) -> bool:
        return self in (CareerLevel.NEWGRAD, CareerLevel.BOTH, CareerLevel.UNKNOWN)


class CaptureMethod(StrEnum):
    API = "api"
    WORKER_SCRAPE = "worker_scrape"
    EXTENSION = "extension"


class JobStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class JobKey:
    """중복 제거의 전부. 이 조합이 안정적이어야 파이프라인 전체가 안정적이다.

    external_id 는 가급적 URL 경로에서 뽑는다. DOM 보다 훨씬 덜 변한다.
    """

    source_id: str
    external_id: str

    def __post_init__(self) -> None:
        if not self.source_id or not self.external_id:
            raise ValueError("source_id 와 external_id 는 필수다")


@dataclass(frozen=True, slots=True)
class RawPosting:
    """정규화 이전의 원본. 파서는 반드시 깨지므로 원본을 버리지 않는다.

    파서를 고친 뒤 페이지를 다시 방문하지 않고 재처리할 수 있어야 한다.
    """

    key: JobKey
    capture_method: CaptureMethod
    payload: Mapping[str, Any]
    html_snapshot: str | None = None
    fetched_at: datetime | None = None
    id: int | None = None

    def truncated(self) -> RawPosting:
        if self.html_snapshot is None or len(self.html_snapshot) <= MAX_HTML_SNAPSHOT:
            return self
        from dataclasses import replace

        return replace(self, html_snapshot=self.html_snapshot[:MAX_HTML_SNAPSHOT])


@dataclass(frozen=True, slots=True)
class JobPosting:
    key: JobKey
    title: str
    url: str
    company: str | None = None
    employment_type: EmploymentType = EmploymentType.UNKNOWN
    career_level: CareerLevel = CareerLevel.UNKNOWN
    location: str | None = None
    deadline: date | None = None
    jd_text: str | None = None
    requirements: tuple[str, ...] = ()
    preferred: tuple[str, ...] = ()
    education: str | None = None      # 학력 조건
    job_field: str | None = None      # NCS 직무분야
    headcount: int | None = None
    status: JobStatus = JobStatus.OPEN
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("title 은 비어 있을 수 없다")
        if not self.url.strip():
            raise ValueError("url 은 비어 있을 수 없다")

    def is_expired(self, today: date) -> bool:
        return self.deadline is not None and self.deadline < today


# ---------------------------------------------------------------- 파싱 결과


@dataclass(frozen=True, slots=True)
class ParseOk:
    posting: JobPosting


@dataclass(frozen=True, slots=True)
class ParseFailed:
    """실패해도 raw 는 남긴다. 파서 수정 후 재시도 대상이 된다."""

    reason: str


ParseResult = ParseOk | ParseFailed


@dataclass(frozen=True, slots=True)
class SourceStatus:
    """ingest_status 툴의 반환 단위.

    추천이 언제 기준 데이터인지 보이지 않으면 사용자가 시스템을 믿지 못한다.
    """

    source_id: str
    last_fetched_at: datetime | None
    open_count: int
    failed_parse_count: int = 0
