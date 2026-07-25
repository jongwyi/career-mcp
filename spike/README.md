# Spike 0 — 원격 MCP 검증

**질문 하나만 답한다:** 챗봇이 *쓰기* 툴을 실제로 호출하는가?

배포하지 않는다. Vercel 적합성은 별개 질문이고, 섞으면 실패했을 때 원인을 못 가린다.

---

## 0. 먼저 확인 (챗봇 화면)

커스텀 MCP 서버를 등록할 자리가 있는지 **세 군데를 모두** 본다. 계정·플랜에 따라 노출 위치가 다르다. 한 곳만 보고 "없다"고 판단하면 시간을 버린다.

- 설정 → 커넥터 / 플러그인
- 설정 → 앱 (또는 개발자 모드 토글)
- GPT 만들기 → Actions

**인증 옵션을 반드시 기록한다.** 확인된 다이얼로그 기준으로 `OAuth / 인증 없음 / 혼합` 세 가지뿐이고 Bearer·API Key 필드가 없다. 이 사실이 ARCHITECTURE.md §4의 전송 계층 설계를 바꾼다.

같은 다이얼로그에 `서버 URL ↔ 터널` 토글이 있으면 **터널 쪽을 우선 시도한다.** cloudflared가 불필요해지고, 서버가 공개 라우팅되지 않아 "인증 없음"의 위험도 크게 낮아진다.

---

## 1. 서버 (터미널 1 — 이 창을 계속 열어둔다)

```bash
uv run --with fastmcp --with uvicorn spike/spike_server.py
```

**이 창이 유일한 판정 근거다.** 챗봇이 "저장했습니다"라고 답해도 여기에 로그가 없으면 호출되지 않은 것이다.

## 2. 터널 (터미널 2)

챗봇에 내장 터널 기능이 있으면 이 단계를 건너뛴다.

```bash
brew install cloudflared
```

```bash
cloudflared tunnel --url http://localhost:8000
```

발급된 `https://xxxx.trycloudflare.com` 뒤에 **`/mcp`를 붙인 주소**를 챗봇에 넣는다. 계정 가입은 필요 없다.

## 3. curl 검증 (터미널 3)

서버가 stateless 모드라 세션 ID 전파가 필요 없다. `-i`로 헤더까지 본다.

```bash
U=https://xxxx.trycloudflare.com/mcp
```

```bash
curl -i -s "$U" -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

```bash
curl -s "$U" -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
```

```bash
curl -s "$U" -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"spike_write","arguments":{"text":"hello"}}}'
```

메모:
- 응답이 `event: message` / `data: {...}` 형태(SSE 프레이밍)로 와도 정상이다.
- 2번에서 툴 3개, 3번에서 터미널 1에 `*** 쓰기 실행됨 ***`이 보이면 **서버는 확실하다.** 이후 실패는 전부 클라이언트 쪽이다.
- `Missing session ID` 오류가 나면 설치된 fastmcp가 `stateless_http`를 지원하지 않는 구버전이다. 1번 응답의 `Mcp-Session-Id` 헤더 값을 이후 요청에 `-H "Mcp-Session-Id: <값>"`으로 실어준다.

## 4. 챗봇 테스트

| 순서 | 지시 | 실패 시 의미 |
|---|---|---|
| 1 | "spike_status 호출해줘" | 연결 자체가 안 됨 |
| 2 | "spike_echo에 hello 넣어줘" | 인자 전달 문제 |
| 3 | "spike_write에 hello 넣어줘" | **쓰기 툴 문제 (핵심 질문)** |
| 4 | "spike_status 다시" | `writes: 1` 확인 |

GPT와 Claude 양쪽에서 같은 주소로 반복한다. 서버 하나로 두 클라이언트를 다 검증할 수 있다.

---

## 판정

터미널 1에 이렇게 찍히면 통과다.

```
[SPIKE 14:23:01] HTTP    POST /mcp  jsonrpc=tools/list
[SPIKE 14:23:15] HTTP    POST /mcp  jsonrpc=tools/call
[SPIKE 14:23:15] WRITE   text='hello'  ->  writes=1   *** 쓰기 실행됨 ***
```

안 찍히면 세 경우를 구분한다. 대응 비용이 전부 다르다.

| 증상 | 원인 | 대응 |
|---|---|---|
| `HTTP` 로그조차 없음 | 연결 실패 (URL·터널·인증) | 접속 설정 |
| `tools/list`는 왔는데 응답에 `spike_write`가 없음 | 플랫폼이 쓰기 툴을 필터링 | **재설계 → Actions 경로** |
| 목록엔 있는데 `tools/call`이 안 옴 | 모델이 호출을 안 함 | description 튜닝 (경미) |

두 번째만 설계 변경 사유다. 세 번째는 그냥 튜닝이다.

---

## 기록할 것

이 spike의 산출물은 "됐다/안 됐다"가 아니라 아래 4개다. ARCHITECTURE.md rev.3에 반영한다.

1. 커스텀 MCP 등록 위치 (커넥터 / 앱 / Actions 중 어디)
2. **인증 선택지** — Bearer 가능 여부, 터널 기능 유무
3. 전송 방식 — `/sse` 인지 streamable HTTP 인지
4. 쓰기 툴 노출 여부
