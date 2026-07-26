"""수집 워커. GitHub Actions 에서 매일 실행된다.

상시 서버가 없으므로 스케줄러 역할을 GH Actions 가 맡는다.
이 파일은 조립과 보고만 한다 — 수집 로직은 core/application/ingest_service.py 에 있다.

로컬 실행:
    uv run --project . python worker/ingest.py
    uv run --project . python worker/ingest.py --full     # 전체 백필
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from adapters.sources.moef import MoefFetcher, MoefParser  # noqa: E402
from adapters.store.supabase_jobs import (  # noqa: E402
    SupabaseJobStore,
    SupabaseRawStore,
)
from core.application.ingest_service import IngestService  # noqa: E402

#: 증분 수집 시 되돌아볼 기간. 공고가 소급 등록되는 경우를 흡수한다.
LOOKBACK_DAYS = 7


def log(message: str) -> None:
    print(f"[ingest {datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


async def run(full: bool, max_pages: int) -> int:
    load_dotenv(ROOT / ".env")
    missing = [
        k
        for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "DATA_GO_KR_SERVICE_KEY")
        if not os.environ.get(k)
    ]
    if missing:
        log(f"환경변수 누락: {', '.join(missing)}")
        return 1

    client = httpx.AsyncClient(timeout=60)
    raw_store = SupabaseRawStore.from_env(client=client)
    job_store = SupabaseJobStore.from_env(client=client)
    fetcher = MoefFetcher(max_pages=max_pages, client=client)
    service = IngestService(raw_store, job_store)

    exit_code = 0
    try:
        status = await job_store.ingest_status()
        known = status.get(MoefParser.source_id)
        if full or known is None:
            since = None
            log("전체 백필 모드")
        else:
            since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
            log(f"증분 모드 — {since:%Y-%m-%d} 이후 공고")

        report = await service.ingest(fetcher, MoefParser(), since=since)
        log(report.summary())

        for error in report.errors[:10]:
            log(f"  오류: {error}")
        if len(report.errors) > 10:
            log(f"  ... 오류 {len(report.errors) - 10}건 더")

        closed = await job_store.close_expired()
        log(f"마감 처리: {closed}건")

        try:
            # 한 문장에 다 지우면 타임아웃이 난다. 0 이 될 때까지 배치로 반복한다.
            total_pruned = 0
            for _ in range(50):
                removed = await raw_store.prune()
                total_pruned += removed
                if removed == 0:
                    break
            log(f"원본 정리: {total_pruned}건 (공고당 최신 1건만 유지)")
        except Exception as exc:
            # 정리 실패가 수집을 실패로 만들지는 않는다.
            log(f"경고: 원본 정리 실패 — {exc}")

        final = await job_store.ingest_status()
        for source_id, info in final.items():
            log(
                f"현황 {source_id}: 진행중 {info.open_count}건 / "
                f"파싱실패 {info.failed_parse_count}건"
            )

        # 조용한 실패를 막는다. API 필터가 바뀌어 0건이 오면 여기서 드러나야 한다.
        if report.fetched == 0:
            log("경고: 수집 0건. API 필터나 응답 형식이 바뀌었을 수 있다.")
            exit_code = 1
        if report.errors:
            exit_code = 1
    except Exception as exc:
        log(f"실패: {type(exc).__name__}: {exc}")
        exit_code = 1
    finally:
        await client.aclose()

    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--full", action="store_true", help="증분이 아니라 전체를 다시 수집한다"
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=int(os.environ.get("INGEST_MAX_PAGES", "80")),
        help="채용구분 코드당 최대 페이지 수 (100건/페이지)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.full, args.max_pages)))


if __name__ == "__main__":
    main()
