"""RawStore / JobStore 의 Supabase(PostgREST) 구현.

프로필 저장소(supabase_store.py)와 파일을 나눈 이유는 수명이 다르기 때문이다.
프로필은 대화가, 공고는 워커가 쓴다. 같이 두면 한쪽 변경이 다른 쪽을 흔든다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from adapters.store.supabase_store import SupabaseClientMixin
from core.domain.job import (
    MAX_HTML_SNAPSHOT,
    CaptureMethod,
    CareerLevel,
    EmploymentType,
    JobKey,
    JobPosting,
    JobStatus,
    RawPosting,
    SourceStatus,
)
from core.domain.match import MatchFilter


class SupabaseRawStore(SupabaseClientMixin):
    """core.ports.store.RawStore 구현."""

    async def append(self, raw: RawPosting) -> RawPosting:
        capped = raw.truncated()
        rows = await self._request(
            "POST",
            "/raw_postings",
            json={
                "source_id": capped.key.source_id,
                "external_id": capped.key.external_id,
                "capture_method": str(capped.capture_method),
                "payload": dict(capped.payload),
                "html_snapshot": capped.html_snapshot,
            },
            prefer="return=representation",
        )
        return self._to_raw(rows[0])

    async def append_many(self, raws: Sequence[RawPosting]) -> Sequence[RawPosting]:
        if not raws:
            return []
        rows = await self._request(
            "POST",
            "/raw_postings",
            json=[
                {
                    "source_id": r.key.source_id,
                    "external_id": r.key.external_id,
                    "capture_method": str(r.capture_method),
                    "payload": dict(r.payload),
                    "html_snapshot": r.html_snapshot,
                }
                for r in (raw.truncated() for raw in raws)
            ],
            prefer="return=representation",
        )
        return [self._to_raw(r) for r in rows]

    async def mark_parsed_many(
        self, raw_ids: Sequence[int], *, ok: bool, reason: str | None = None
    ) -> None:
        if not raw_ids:
            return
        await self._request(
            "PATCH",
            "/raw_postings",
            params={"id": f"in.({','.join(str(i) for i in raw_ids)})"},
            json={
                "parse_status": "ok" if ok else "failed",
                "parse_reason": None if ok else (reason or "")[:500],
            },
            prefer="return=minimal",
        )

    async def prune(self, *, batch_limit: int = 2000) -> int:
        removed = await self._request(
            "POST", "/rpc/prune_raw_postings", json={"batch_limit": batch_limit}
        )
        return int(removed or 0)

    async def list_unparsed(self, *, limit: int = 100) -> Sequence[RawPosting]:
        rows = await self._request(
            "GET",
            "/raw_postings",
            params={
                "select": "*",
                "parse_status": "neq.ok",
                "order": "fetched_at.asc",
                "limit": str(limit),
            },
        )
        return [self._to_raw(r) for r in rows]

    async def mark_parsed(
        self, raw_id: int, *, ok: bool, reason: str | None = None
    ) -> None:
        await self._request(
            "PATCH",
            "/raw_postings",
            params={"id": f"eq.{raw_id}"},
            json={
                "parse_status": "ok" if ok else "failed",
                "parse_reason": None if ok else (reason or "")[:500],
            },
            prefer="return=minimal",
        )

    @staticmethod
    def _to_raw(row: Mapping[str, Any]) -> RawPosting:
        fetched = row.get("fetched_at")
        return RawPosting(
            id=row["id"],
            key=JobKey(row["source_id"], row["external_id"]),
            capture_method=CaptureMethod(row["capture_method"]),
            payload=row.get("payload") or {},
            html_snapshot=row.get("html_snapshot"),
            fetched_at=datetime.fromisoformat(fetched) if fetched else None,
        )


class SupabaseJobStore(SupabaseClientMixin):
    """core.ports.store.JobStore 구현."""

    async def upsert(self, posting: JobPosting) -> JobPosting:
        # first_seen 은 payload 에 넣지 않는다. 넣으면 재수집마다 초기화된다.
        # PostgREST 는 payload 에 있는 컬럼만 ON CONFLICT DO UPDATE SET 에 넣는다.
        rows = await self._request(
            "POST",
            "/jobs",
            params={"on_conflict": "source_id,external_id"},
            json=self._to_row(posting),
            prefer="resolution=merge-duplicates,return=representation",
        )
        return self._to_posting(rows[0])

    async def upsert_many(
        self, postings: Sequence[JobPosting]
    ) -> Sequence[JobPosting]:
        if not postings:
            return []
        # 같은 배치 안에 같은 키가 두 번 있으면 Postgres 가
        # "ON CONFLICT DO UPDATE command cannot affect row a second time" 로 죽는다.
        deduped: dict[tuple[str, str], JobPosting] = {}
        for posting in postings:
            deduped[(posting.key.source_id, posting.key.external_id)] = posting
        rows = await self._request(
            "POST",
            "/jobs",
            params={"on_conflict": "source_id,external_id"},
            json=[self._to_row(p) for p in deduped.values()],
            prefer="resolution=merge-duplicates,return=representation",
        )
        return [self._to_posting(r) for r in rows]

    async def get(self, job_id: int) -> JobPosting | None:
        rows = await self._request(
            "GET", "/jobs", params={"id": f"eq.{job_id}", "select": "*"}
        )
        return self._to_posting(rows[0]) if rows else None

    async def search(self, flt: MatchFilter) -> Sequence[JobPosting]:
        rows = await self._request("GET", "/jobs", params=self._search_params(flt))
        return [self._to_posting(r) for r in rows]

    @staticmethod
    def _search_params(flt: MatchFilter) -> dict[str, str]:
        params: dict[str, str] = {
            "select": "*",
            "order": "deadline.asc.nullslast",
            "limit": str(flt.limit),
        }
        if not flt.include_closed:
            params["status"] = "eq.open"
        if flt.employment_types:
            params["employment_type"] = (
                f"in.({','.join(str(t) for t in flt.employment_types)})"
            )
        if flt.career_levels:
            params["career_level"] = (
                f"in.({','.join(str(c) for c in flt.career_levels)})"
            )
        if not flt.include_restricted:
            params["restrictions"] = "eq.{}"
        if flt.location:
            params["location"] = f"ilike.*{flt.location}*"
        if flt.deadline_after:
            # 마감일이 없는 공고(상시채용 등)를 버리지 않는다.
            params["or"] = f"(deadline.gte.{flt.deadline_after.isoformat()},deadline.is.null)"
        if flt.keyword:
            # 한국어는 to_tsvector('simple') 로 어간 분리가 안 되므로
            # 부분 일치(ilike)가 오히려 실용적이다. 수천 건 규모에서 충분히 빠르다.
            kw = flt.keyword.replace("*", "")
            key = "or" if "or" not in params else "and"
            clause = f"(title.ilike.*{kw}*,jd_text.ilike.*{kw}*,job_field.ilike.*{kw}*)"
            if key == "or":
                params["or"] = clause
            else:
                params["and"] = f"(or{clause})"
        return params

    async def count(self, flt: MatchFilter) -> int:
        params = self._search_params(flt)
        params.pop("limit", None)
        params.pop("order", None)
        params.pop("select", None)
        return await self._count("/jobs", params)

    async def mark_closed(self, keys: Sequence[JobKey]) -> int:
        closed = 0
        for key in keys:
            await self._request(
                "PATCH",
                "/jobs",
                params={
                    "source_id": f"eq.{key.source_id}",
                    "external_id": f"eq.{key.external_id}",
                },
                json={"status": "closed"},
                prefer="return=minimal",
            )
            closed += 1
        return closed

    async def close_expired(self, today: date | None = None) -> int:
        """마감일이 지난 공고를 일괄 정리한다. 워커가 매 실행마다 부른다."""
        cutoff = (today or date.today()).isoformat()
        rows = await self._request(
            "PATCH",
            "/jobs",
            params={"status": "eq.open", "deadline": f"lt.{cutoff}"},
            json={"status": "closed"},
            prefer="return=representation",
        )
        return len(rows or [])

    async def ingest_status(self) -> Mapping[str, SourceStatus]:
        sources = {
            r["source_id"]
            for r in await self._request(
                "GET", "/raw_postings", params={"select": "source_id"}
            )
        }
        result: dict[str, SourceStatus] = {}
        for source_id in sorted(sources):
            latest = await self._request(
                "GET",
                "/raw_postings",
                params={
                    "select": "fetched_at",
                    "source_id": f"eq.{source_id}",
                    "order": "fetched_at.desc",
                    "limit": "1",
                },
            )
            open_count = await self._count(
                "/jobs", {"source_id": f"eq.{source_id}", "status": "eq.open"}
            )
            failed = await self._count(
                "/raw_postings",
                {"source_id": f"eq.{source_id}", "parse_status": "eq.failed"},
            )
            result[source_id] = SourceStatus(
                source_id=source_id,
                last_fetched_at=(
                    datetime.fromisoformat(latest[0]["fetched_at"]) if latest else None
                ),
                open_count=open_count,
                failed_parse_count=failed,
            )
        return result

    # ---------------------------------------------------------------- 매핑

    @staticmethod
    def _to_row(posting: JobPosting) -> dict[str, Any]:
        return {
            "source_id": posting.key.source_id,
            "external_id": posting.key.external_id,
            "title": posting.title,
            "url": posting.url,
            "company": posting.company,
            "employment_type": str(posting.employment_type),
            "career_level": str(posting.career_level),
            "location": posting.location,
            "deadline": posting.deadline.isoformat() if posting.deadline else None,
            "jd_text": posting.jd_text,
            "requirements": list(posting.requirements),
            "preferred": list(posting.preferred),
            "education": posting.education,
            "job_field": posting.job_field,
            "headcount": posting.headcount,
            "restrictions": list(posting.restrictions),
            "status": str(posting.status),
            "last_seen": datetime.now().astimezone().isoformat(),
        }

    @staticmethod
    def _to_posting(row: Mapping[str, Any]) -> JobPosting:
        def dt(value: Any) -> datetime | None:
            return datetime.fromisoformat(value) if value else None

        return JobPosting(
            id=row["id"],
            key=JobKey(row["source_id"], row["external_id"]),
            title=row["title"],
            url=row["url"],
            company=row.get("company"),
            employment_type=EmploymentType(row.get("employment_type", "unknown")),
            career_level=CareerLevel(row.get("career_level", "unknown")),
            location=row.get("location"),
            deadline=date.fromisoformat(row["deadline"]) if row.get("deadline") else None,
            jd_text=row.get("jd_text"),
            requirements=tuple(row.get("requirements") or ()),
            preferred=tuple(row.get("preferred") or ()),
            education=row.get("education"),
            job_field=row.get("job_field"),
            headcount=row.get("headcount"),
            restrictions=tuple(row.get("restrictions") or ()),
            status=JobStatus(row.get("status", "open")),
            first_seen=dt(row.get("first_seen")),
            last_seen=dt(row.get("last_seen")),
        )


__all__ = ["SupabaseRawStore", "SupabaseJobStore", "MAX_HTML_SNAPSHOT"]
