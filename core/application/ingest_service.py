"""수집 유스케이스. 모든 소스가 이 경로 하나를 지난다.

    fetch → raw_postings 적재 → parse → jobs upsert

공식 API든 크롬 확장이든 워커 스크랩이든 정규화 경로는 하나다.
원본을 먼저 적재하는 이유는 파서가 반드시 깨지기 때문이다 —
파서를 고친 뒤 재수집 없이 reparse_failed 로 되살릴 수 있어야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from core.domain.job import ParseOk
from core.ports.source import PostingFetcher, PostingParser
from core.ports.store import JobStore, RawStore


@dataclass
class IngestReport:
    source_id: str
    fetched: int = 0
    parsed_ok: int = 0
    parse_failed: int = 0
    upserted: int = 0
    truncated: bool = False  # 페이지 상한에 걸려 일부만 가져왔는가
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        base = (
            f"{self.source_id}: 수집 {self.fetched} / 파싱 성공 {self.parsed_ok} "
            f"실패 {self.parse_failed} / 저장 {self.upserted}"
        )
        return base + (" [상한 도달 — 일부만 수집됨]" if self.truncated else "")


class IngestService:
    def __init__(self, raw_store: RawStore, job_store: JobStore) -> None:
        self._raw = raw_store
        self._jobs = job_store

    async def ingest(
        self,
        fetcher: PostingFetcher,
        parser: PostingParser,
        *,
        since: datetime | None = None,
    ) -> IngestReport:
        report = IngestReport(source_id=fetcher.source_id)

        async for raw in fetcher.fetch(since):
            report.fetched += 1
            try:
                stored = await self._raw.append(raw)
            except Exception as exc:
                report.errors.append(f"raw 적재 실패 {raw.key.external_id}: {exc}")
                continue

            await self._apply(stored, parser, report)

        return report

    async def reparse_failed(
        self, parser: PostingParser, *, limit: int = 200
    ) -> IngestReport:
        """파서를 고친 뒤 실패분을 되살린다. 원본을 다시 받지 않는다."""
        report = IngestReport(source_id=parser.source_id)
        pending = await self._raw.list_unparsed(limit=limit)
        for raw in pending:
            if raw.key.source_id != parser.source_id:
                continue
            report.fetched += 1
            await self._apply(raw, parser, report)
        return report

    async def _apply(self, raw, parser: PostingParser, report: IngestReport) -> None:
        result = parser.parse(raw)
        if not isinstance(result, ParseOk):
            report.parse_failed += 1
            if raw.id is not None:
                await self._raw.mark_parsed(raw.id, ok=False, reason=result.reason)
            return

        report.parsed_ok += 1
        try:
            await self._jobs.upsert(result.posting)
            report.upserted += 1
            if raw.id is not None:
                await self._raw.mark_parsed(raw.id, ok=True)
        except Exception as exc:
            # 저장 실패는 파싱 실패와 다르다. raw 를 pending 으로 남겨 재시도한다.
            report.errors.append(f"저장 실패 {raw.key.external_id}: {exc}")
