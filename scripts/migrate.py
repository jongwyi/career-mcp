"""마이그레이션 실행기.

    uv run --with "psycopg[binary]" --with python-dotenv scripts/migrate.py
    uv run ... scripts/migrate.py --status     # 적용 현황만
    uv run ... scripts/migrate.py --mark 001   # 이미 수동 적용한 것을 기록만

Supabase SQL Editor 에 붙여넣는 과정을 없앤다. 편집기가 마지막 세미콜론 뒤
빈 문장을 실행하려다 내는 가짜 오류(`LINE 0: syntax error at end of input`)도
여기서는 발생하지 않는다.

접속은 **풀러**를 쓴다. 신규 Supabase 프로젝트의 직접 접속 호스트
(db.<ref>.supabase.co)는 IPv6 전용이라 환경에 따라 resolve 되지 않는다.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "migrations"

import psycopg  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

TRACKING = """
create table if not exists schema_migrations (
  version    text primary key,
  applied_at timestamptz not null default now()
)
"""


def files() -> list[Path]:
    return sorted(MIGRATIONS.glob("*.sql"))


def version_of(path: Path) -> str:
    return path.stem.split("_", 1)[0]


def connect() -> psycopg.Connection:
    load_dotenv(ROOT / ".env")
    dsn = os.environ.get("SUPABASE_DB_URL", "")
    if not dsn:
        raise SystemExit(
            ".env 에 SUPABASE_DB_URL 이 없다.\n"
            "Supabase 대시보드 > Connect > Session pooler 의 문자열을 넣을 것.\n"
            "  SUPABASE_DB_URL=postgresql://postgres.<ref>:<password>"
            "@aws-0-<region>.pooler.supabase.com:5432/postgres"
        )
    return psycopg.connect(dsn, connect_timeout=20, autocommit=True)


def applied(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(TRACKING)
        cur.execute("select version from schema_migrations")
        return {r[0] for r in cur.fetchall()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true", help="적용 현황만 보여준다")
    parser.add_argument("--mark", nargs="*", help="실행하지 않고 적용됨으로 기록만")
    args = parser.parse_args()

    with connect() as conn:
        done = applied(conn)

        if args.mark:
            with conn.cursor() as cur:
                for v in args.mark:
                    cur.execute(
                        "insert into schema_migrations(version) values (%s) "
                        "on conflict do nothing",
                        (v,),
                    )
            print(f"기록 완료: {', '.join(args.mark)}")
            return

        if args.status:
            for path in files():
                v = version_of(path)
                print(f"  {'✓' if v in done else ' '} {path.name}")
            return

        pending = [p for p in files() if version_of(p) not in done]
        if not pending:
            print("적용할 마이그레이션이 없다.")
            return

        for path in pending:
            v = version_of(path)
            sql = path.read_text(encoding="utf-8")
            print(f"  적용 중: {path.name} ... ", end="", flush=True)
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    cur.execute(
                        "insert into schema_migrations(version) values (%s) "
                        "on conflict do nothing",
                        (v,),
                    )
                print("OK")
            except Exception as exc:
                print("실패")
                print(f"    {type(exc).__name__}: {exc}")
                # 하나가 실패하면 멈춘다. 순서가 있는 변경이라 건너뛰면 안 된다.
                sys.exit(1)
        print(f"완료: {len(pending)}건 적용")


if __name__ == "__main__":
    main()
