"""재정경제부 공공기관 채용정보 (잡알리오) 어댑터.

https://www.data.go.kr/data/15125273/openapi.do
개발계정 자동승인 · 1,000건/일 · JSON · 이용허락범위 제한 없음

목록 엔드포인트가 이미 전체 필드를 반환하므로 상세 호출을 하지 않는다.
호출 수가 공고 수만큼이 아니라 페이지 수만큼만 든다.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Any

import httpx

from adapters.sources.moef_codes import (
    EDUCATION_BY_CODE,
    INTERN_CODES,
    NEWGRAD_CODES,
    career_level_of,
    employment_type_of,
)
from core.domain.job import (
    CaptureMethod,
    JobKey,
    JobPosting,
    JobStatus,
    ParseFailed,
    ParseOk,
    ParseResult,
    RawPosting,
)
from core.domain.restriction import detect_restrictions

SOURCE_ID = "moef"
BASE_URL = "https://apis.data.go.kr/1051000/recruitment"
PAGE_SIZE = 100


class MoefFetcher:
    """core.ports.source.PostingFetcher 구현."""

    source_id = SOURCE_ID

    def __init__(
        self,
        service_key: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        max_pages: int = 20,
    ) -> None:
        self._key = service_key or os.environ.get("DATA_GO_KR_SERVICE_KEY", "")
        if not self._key:
            raise ValueError("DATA_GO_KR_SERVICE_KEY 가 필요하다")
        self._client = client or httpx.AsyncClient(timeout=30)
        # 일일 한도 1,000 건을 넘지 않도록 상한을 둔다.
        # 조용히 잘리면 "다 모았다"고 착각하게 되므로 worker 가 이 값을 로그에 남긴다.
        self._max_pages = max_pages

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch(self, since: datetime | None = None) -> AsyncIterator[RawPosting]:
        """인턴 + 신입 지원 가능 공고만 가져온다.

        **`recrutSe` 는 쉼표 목록을 받지 않는다.** 여러 값을 넘기면 오류가 아니라
        `resultCode=200, totalCount=0` 을 돌려준다. 크론에서 이러면
        "오늘은 새 공고가 없다"로 보여 몇 주를 모른 채 지나간다.
        그래서 코드별로 나눠 호출한다. (`hireTypeLst` 는 쉼표를 받는다.)

        정렬이 공고번호 내림차순(최신순)이라 since 이전 공고를 만나면 그 코드를 끝낸다.
        """
        cutoff = since.date() if since else None

        for recruit_code in NEWGRAD_CODES:
            async for raw in self._fetch_one(recruit_code, cutoff):
                yield raw

    async def _fetch_one(
        self, recruit_code: str, cutoff: date | None
    ) -> AsyncIterator[RawPosting]:
        for page in range(1, self._max_pages + 1):
            payload = await self._get(
                "/list",
                {
                    "numOfRows": PAGE_SIZE,
                    "pageNo": page,
                    "hireTypeLst": ",".join(INTERN_CODES),
                    "recrutSe": recruit_code,
                },
            )
            rows = payload.get("result") or []
            if not rows:
                return

            for row in rows:
                if cutoff is not None:
                    begun = _parse_ymd(row.get("pbancBgngYmd"))
                    if begun is not None and begun < cutoff:
                        return
                external_id = str(row.get("recrutPblntSn") or "").strip()
                if not external_id:
                    continue
                yield RawPosting(
                    key=JobKey(SOURCE_ID, external_id),
                    capture_method=CaptureMethod.API,
                    payload=row,
                )

            if len(rows) < PAGE_SIZE:
                return

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = {"serviceKey": self._key, "resultType": "json", **params}
        response = await self._client.get(f"{BASE_URL}{path}", params=query)
        response.raise_for_status()
        payload = response.json()
        if payload.get("resultCode") not in (200, "200", None):
            raise RuntimeError(
                f"MOEF API 오류: {payload.get('resultCode')} {payload.get('resultMsg')}"
            )
        return payload


class MoefParser:
    """core.ports.source.PostingParser 구현. 네트워크를 쓰지 않는 순수 변환."""

    source_id = SOURCE_ID

    def parse(self, raw: RawPosting) -> ParseResult:
        row = raw.payload
        try:
            title = (row.get("recrutPbancTtl") or "").strip()
            if not title:
                return ParseFailed("recrutPbancTtl 이 비어 있다")

            deadline = _parse_ymd(row.get("pbancEndYmd"))
            url = (row.get("srcUrl") or "").strip()
            if not url:
                # srcUrl 은 기관 홈페이지인 경우가 많고 드물게 비어 있다.
                # 링크가 없으면 사용자가 지원할 수 없으므로 기관명으로라도 남긴다.
                url = f"https://job.alio.go.kr/recruit.do?keyword={row.get('instNm','')}"

            requirements = _lines(row.get("aplyQlfcCn"))
            company = row.get("instNm") or None
            posting = JobPosting(
                key=raw.key,
                title=title,
                url=url,
                company=company,
                employment_type=employment_type_of(row.get("hireTypeLst")),
                career_level=career_level_of(row.get("recrutSe")),
                location=(row.get("workRgnNmLst") or None),
                deadline=deadline,
                jd_text=_build_jd_text(row),
                requirements=requirements,
                preferred=_lines(row.get("prefCn") or row.get("prefCondCn")),
                education=_education(row),
                job_field=(row.get("ncsCdNmLst") or None),
                headcount=_int_or_none(row.get("recrutNope")),
                status=_status(row, deadline),
                restrictions=detect_restrictions(
                    title, company=company, requirements=requirements
                ),
            )
            return ParseOk(posting)
        except Exception as exc:  # 한 건의 실패가 나머지를 막지 않는다
            return ParseFailed(f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------- 헬퍼


def _parse_ymd(value: Any) -> date | None:
    text = str(value or "").strip()
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:]))
    except ValueError:
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _lines(value: Any) -> tuple[str, ...]:
    """긴 서술형 텍스트를 항목으로 쪼갠다.

    매칭 단계에서 LLM 이 요건 단위로 대조할 수 있어야 하므로,
    통짜 문자열보다 항목 배열이 낫다.
    """
    text = str(value or "").strip()
    if not text:
        return ()
    parts: list[str] = []
    for chunk in text.replace("\r", "\n").split("\n"):
        chunk = chunk.strip(" ·-○▶□■*\t")
        if len(chunk) >= 3:
            parts.append(chunk)
    return tuple(parts[:40])


def _education(row: dict[str, Any]) -> str | None:
    name = (row.get("acbgCondNmLst") or "").strip()
    if name:
        return name
    codes = (row.get("acbgCondLst") or "").strip()
    if not codes:
        return None
    return ",".join(
        EDUCATION_BY_CODE.get(c.strip(), c.strip()) for c in codes.split(",")
    ) or None


def _status(row: dict[str, Any], deadline: date | None) -> JobStatus:
    if str(row.get("ongoingYn") or "").upper() == "N":
        return JobStatus.CLOSED
    if deadline is not None and deadline < date.today():
        return JobStatus.CLOSED
    return JobStatus.OPEN


def _build_jd_text(row: dict[str, Any]) -> str:
    """전문 검색(FTS)과 LLM 대조에 쓸 본문."""
    sections = [
        ("직무분야", row.get("ncsCdNmLst")),
        ("고용형태", row.get("hireTypeNmLst")),
        ("채용구분", row.get("recrutSeNm")),
        ("학력", row.get("acbgCondNmLst")),
        ("근무지", row.get("workRgnNmLst")),
        ("지원자격", row.get("aplyQlfcCn")),
        ("우대사항", row.get("prefCn") or row.get("prefCondCn")),
        ("전형방법", row.get("scrnprcdrMthdExpln")),
        ("결격사유", row.get("disqlfcRsn")),
    ]
    return "\n\n".join(
        f"[{label}]\n{str(value).strip()}"
        for label, value in sections
        if value and str(value).strip() and str(value).strip() != "None"
    )
