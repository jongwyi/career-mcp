"""ChatGPT / Claude 원격 MCP 검증용 최소 서버. 일회용 스파이크.

목적: "챗봇이 쓰기(write) 툴을 실제로 호출하는가"를 증명한다.
판정 근거는 챗봇 화면이 아니라 이 터미널의 로그다.
모델은 툴을 부르지 않고도 "저장했습니다"라고 답할 수 있다.

실행:
    uv run --with fastmcp --with uvicorn spike_server.py
"""

import json
import sys
from datetime import datetime

from fastmcp import FastMCP

# stateless: 세션 ID 전파가 불필요해져 curl 검증이 단순해지고,
# 최종 목표인 서버리스 환경과 동일한 모드가 된다.
try:
    mcp = FastMCP("spike", stateless_http=True)
except TypeError:  # 구버전 fastmcp
    mcp = FastMCP("spike")

_state = {"memo": "(비어있음)", "writes": 0, "calls": 0}


def log(msg: str) -> None:
    print(f"[SPIKE {datetime.now():%H:%M:%S}] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- tools

@mcp.tool()
def spike_status() -> dict:
    """스파이크 서버의 현재 상태와 호출 횟수를 반환한다. 연결 확인용."""
    _state["calls"] += 1
    log(f"status  (writes={_state['writes']}, memo={_state['memo']!r})")
    return {
        "ok": True,
        "writes": _state["writes"],
        "total_calls": _state["calls"],
        "memo": _state["memo"],
    }


@mcp.tool()
def spike_echo(text: str) -> str:
    """받은 텍스트를 그대로 돌려준다. 상태를 바꾸지 않는다. 인자 전달 확인용."""
    _state["calls"] += 1
    log(f"echo    text={text!r}")
    return text


@mcp.tool()
def spike_write(text: str) -> str:
    """메모를 저장하고 쓰기 횟수를 1 증가시킨다. 서버 상태를 변경한다."""
    _state["calls"] += 1
    _state["writes"] += 1
    _state["memo"] = text
    log(f"WRITE   text={text!r}  ->  writes={_state['writes']}   *** 쓰기 실행됨 ***")
    return f"저장 완료. memo={text!r}, writes={_state['writes']}"


# ------------------------------------------------- HTTP 요청 로깅 미들웨어
# 툴 호출 로그만으로는 "연결 실패"와 "연결됐지만 툴을 안 부름"이 구분되지 않는다.
# 모든 JSON-RPC method를 찍어서 tools/list 도착 여부를 눈으로 확인한다.

class LogMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        chunks, more = [], True
        while more:
            msg = await receive()
            if msg["type"] == "http.request":
                chunks.append(msg.get("body", b""))
                more = msg.get("more_body", False)
            else:
                more = False
        body = b"".join(chunks)

        method = "-"
        try:
            parsed = json.loads(body) if body else None
            if isinstance(parsed, list):
                method = ",".join(str(p.get("method")) for p in parsed)
            elif isinstance(parsed, dict):
                method = str(parsed.get("method", "-"))
        except Exception:
            pass
        log(f"HTTP    {scope['method']} {scope['path']}  jsonrpc={method}")

        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def build_app():
    """fastmcp 버전에 따라 ASGI 앱 생성 메서드 이름이 다르다."""
    for name in ("http_app", "streamable_http_app"):
        factory = getattr(mcp, name, None)
        if factory is None:
            continue
        try:
            return factory()
        except TypeError:
            continue
    return None


if __name__ == "__main__":
    log("서버 시작 -> http://127.0.0.1:8000/mcp")
    app = build_app()
    if app is not None:
        import uvicorn
        uvicorn.run(LogMiddleware(app), host="127.0.0.1", port=8000, log_level="warning")
    else:
        # 폴백: 미들웨어 로깅 없이 실행 (툴 호출 로그만 보임)
        log("경고: ASGI 앱 생성 실패. HTTP 요청 로깅 없이 실행한다.")
        try:
            mcp.run(transport="http", host="127.0.0.1", port=8000)
        except (TypeError, ValueError):
            mcp.run(transport="streamable-http", host="127.0.0.1", port=8000)
