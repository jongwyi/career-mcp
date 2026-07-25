"""수집 유스케이스. 모든 소스가 이 경로 하나를 지난다.

    fetch → raw_postings 적재 → parse → jobs upsert

공식 API든 크롬 확장이든 워커 스크랩이든 정규화 경로는 하나다.
원본을 먼저 적재하는 이유는 파서가 반드시 깨지기 때문이다 —
파서를 고친 뒤 재수집 없이 reparse_failed 로 되살릴 수 있어야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from core.domain.job import ParseOk, RawPosting
from core.ports.source import PostingFetcher, PostingParser
from core.ports.store import JobStore, RawStore

#: 한 번에 묶어 보낼 건수. PostgREST 요청 크기와 왕복 수의 절충점이다.
BATCH_SIZE = 200


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
        batch_size: int = BATCH_SIZE,
    ) -> IngestReport:
        """배치로 처리한다.

        건당 왕복 3회(raw 삽입 / job upsert / 파싱 표시)로 하면
        1만 건에 3만 요청, 40분이 걸린다. GH Actions 30분 제한을 넘는다.
        배치로 묶으면 요청 수가 건수가 아니라 배치 수에 비례한다.
        """
        report = IngestReport(source_id=fetcher.source_id)
        buffer: list[RawPosting] = []

        async for raw in fetcher.fetch(since):
            report.fetched += 1
            buffer.append(raw)
            if len(buffer) >= batch_size:
                await self._flush(buffer, parser, report)
                buffer = []

        if buffer:
            await self._flush(buffer, parser, report)
        return report

    async def _flush(
        self,
        batch: list[RawPosting],
        parser: PostingParser,
        report: IngestReport,
    ) -> None:
        try:
            stored = await self._raw.append_many(batch)
        except Exception as exc:
            report.errors.append(f"raw 배치 적재 실패 ({len(batch)}건): {exc}")
            return

        postings = []
        ok_ids: list[int] = []
        for raw in stored:
            result = parser.parse(raw)
            if isinstance(result, ParseOk):
                report.parsed_ok += 1
                postings.append(result.posting)
                if raw.id is not None:
                    ok_ids.append(raw.id)
            else:
                report.parse_failed += 1
                if raw.id is not None:
                    await self._raw.mark_parsed(
                        raw.id, ok=False, reason=result.reason
                    )

        if not postings:
            return
        try:
            saved = await self._jobs.upsert_many(postings)
            report.upserted += len(saved)
            # 저장이 끝난 뒤에 표시한다. 순서를 뒤집으면 저장 실패분이
            # ok 로 남아 재시도 대상에서 빠진다.
            await self._raw.mark_parsed_many(ok_ids, ok=True)
        except Exception as exc:
            # 저장 실패는 파싱 실패와 다르다. raw 를 pending 으로 남겨 재시도한다.
            report.errors.append(f"저장 배치 실패 ({len(postings)}건): {exc}")

    async def reparse_failed(
        self, parser: PostingParser, *, limit: int = BATCH_SIZE
    ) -> IngestReport:
        """파서를 고친 뒤 실패분을 되살린다. 원본을 다시 받지 않는다."""
        report = IngestReport(source_id=parser.source_id)
        pending = [
            raw
            for raw in await self._raw.list_unparsed(limit=limit)
            if raw.key.source_id == parser.source_id
        ]
        report.fetched = len(pending)

        postings = []
        ok_ids: list[int] = []
        for raw in pending:
            result = parser.parse(raw)
            if isinstance(result, ParseOk):
                report.parsed_ok += 1
                postings.append(result.posting)
                if raw.id is not None:
                    ok_ids.append(raw.id)
            else:
                report.parse_failed += 1
                if raw.id is not None:
                    await self._raw.mark_parsed(raw.id, ok=False, reason=result.reason)

        if postings:
            try:
                saved = await self._jobs.upsert_many(postings)
                report.upserted += len(saved)
                await self._raw.mark_parsed_many(ok_ids, ok=True)
            except Exception as exc:
                report.errors.append(f"저장 배치 실패 ({len(postings)}건): {exc}")
        return report
