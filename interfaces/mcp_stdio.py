"""Claude Desktop / Claude Code 용 MCP 서버 (stdio).

실행:
    uv run --with fastmcp --with httpx --with python-dotenv interfaces/mcp_stdio.py

이 파일에는 비즈니스 로직을 두지 않는다. 조립과 위임만 한다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 저장소 루트를 import 경로에 넣는다 (Claude 가 임의 디렉토리에서 실행한다)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
from fastmcp import FastMCP  # noqa: E402

from adapters.store.supabase_store import SupabaseProfileStore  # noqa: E402
from core.application.import_service import ImportService  # noqa: E402
from core.application.profile_service import ProfileService  # noqa: E402
from interfaces.tool_registry import build_profile_tools, register  # noqa: E402


def build_server() -> FastMCP:
    load_dotenv(ROOT / ".env")

    missing = [
        k for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY") if not os.environ.get(k)
    ]
    if missing:
        raise SystemExit(
            f".env 에 다음이 없다: {', '.join(missing)}\n"
            f"확인 위치: {ROOT / '.env'}"
        )

    store = SupabaseProfileStore.from_env()
    mcp = FastMCP("career")
    register(mcp, build_profile_tools(ProfileService(store), ImportService(store)))
    return mcp


if __name__ == "__main__":
    build_server().run()
