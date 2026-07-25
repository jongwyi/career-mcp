# 보류 — ChatGPT 실시간 연동 설계

> **상태: 보류.** ChatGPT Free 플랜에서는 구현 불가.
> 유료 전환 시 이 문서부터 읽으면 재조사 없이 착수할 수 있다.
> 조사 시점: 2026-07-25

현재 채택된 경로는 파일 임포트다 → [PROFILE_IMPORT_FORMAT.md](PROFILE_IMPORT_FORMAT.md)

---

## 1. 왜 보류인가

| 경로 | 필요 플랜 |
|---|---|
| 커스텀 MCP 앱 (개발자 모드) | **Pro / Plus / Business / Enterprise / Edu** — Free 불가 |
| Custom GPT + Actions | **Plus 이상** (Free는 남의 GPT 사용만 가능) |

두 경로 모두 Free에서 닫힌다. 무료로 우회할 방법은 조사 범위에서 발견되지 않았다.

## 2. 확정된 제약 (재조사 불필요)

### Bearer / API Key 헤더는 불가능하다

Apps SDK 인증 문서 원문에 명시적 부정문이 있다 — ChatGPT는 client credentials, service account, JWT bearer assertion, 커스텀 API 키, 고객 제공 mTLS 인증서를 **제시하지 못한다.**

등록 다이얼로그의 인증 선택지는 셋뿐이다.

| 옵션 | 의미 |
|---|---|
| `OAuth` | 정적 credential 입력 가능. 또는 CIMD / DCR |
| `인증 없음` | 익명 호출 |
| `혼합(MIXED)` | `initialize`·`tools/list`는 무인증, 개별 툴은 `_meta.securitySchemes`에 따라 OAuth 또는 무인증 (**툴 단위 혼합**) |

### Secure Tunnel은 무료 우회로가 아니다

내부망 MCP 서버를 공개 URL 없이 연결하는 기능이고 아웃바운드 전용이라 방화벽은 안 열어도 된다. 하지만:

- **결제되는 OpenAI Platform API 키**(`sk-...`)가 필요하다
- `tunnel-client` 프로세스가 계속 떠 있어야 한다 → "상시 서버 없음" 제약을 해결하지 못한다
- OAuth 요구를 대체하지 않는다

### 무인증은 Claude 쪽에서 깨진다

Claude.ai는 원격 MCP에 OAuth 2.1을 가정하고 DCR을 시도하며, 관리 UI에 무인증을 선언할 방법이 없다는 이슈가 열려 있다. ChatGPT에서만 되고 Claude에서 안 되면 공유 저장소라는 전제가 무너진다.

추가로, 인터넷 노출 MCP 서버의 약 40%가 무인증이고 실제 공격 체인(툴 목록 노출 → 브라우저 구동 툴 악용 → 호스트 파일 읽기)이 시연된 바 있다. `/mcp/<랜덤 32바이트>` 같은 비밀 URL은 사실상 URL에 박은 bearer 토큰이고 로그·리퍼러로 샌다.

### 기타

- **전송**: SSE와 Streamable HTTP 둘 다 지원. 신규는 Streamable HTTP 권장 (SSE는 스펙상 deprecated)
- **쓰기 툴**: 개발자 모드에서 허용됨. 호출마다 확인 카드가 뜨고, `readOnlyHint` 없는 툴은 전부 쓰기로 간주. 단 "쓰기는 Business 이상"이라는 2차 출처 주장이 있고 공식 문서에는 그 구분이 없다 → **미검증. 유료 전환 시 spike로 확인할 것**
- **설정 경로**: `Settings → Security and login → Developer mode` 토글 → `Settings → Plugins` 또는 `chatgpt.com/plugins`의 `+`. UI 명칭이 Connectors → Apps → Plugins로 이동 중이라 문서마다 다르게 적혀 있다

## 3. 채택 예정 경로 — WorkOS AuthKit + FastMCP

OAuth를 직접 구현할 필요가 없다. **파일 2개, 1~2시간.** 대부분 대시보드 설정이다.

```
ChatGPT / Claude
   │  OAuth 2.1 + PKCE
   ▼
WorkOS AuthKit (AS)          ← authorization code, DCR/CIMD, refresh token 전부 보관
   │  JWT (aud = 서버 resource URL)
   ▼
FastMCP 서버 (RS)            ← 하는 일: PRM 서빙 + JWT 서명 검증. 그게 전부
   ▼
Supabase (DB 전용)
```

**핵심 장점: 서버가 저장할 인증 상태가 0이다.** 서버리스 무료 티어와 정확히 맞는다.

DCR과 CIMD를 모두 지원해 ChatGPT·Claude 양쪽이 수동 client_id 입력 없이 붙는다. RFC 8707 `resource` 바인딩을 지원해 FastMCP가 `aud` 클레임을 자동 검증한다.

### 탈락한 대안들과 이유

| 경로 | 막히는 지점 |
|---|---|
| Supabase를 AS로 | RFC 8707 미지원 → audience 검증 불가(스펙 MUST 위반). 동의 화면 직접 제작 필요. **무료 프로젝트 7일 일시정지가 인증 자체를 끊음** |
| FastMCP `OAuthProxy` + GitHub | 공식 문서가 "서버리스에 부적합"이라고 명시. 영속 스토리지 필요 |
| Auth0 | DCR 기본 비활성 + Resource Parameter Compatibility Profile 필요. 무료 티어 DCR 가부 불명확 |
| 직접 구현 | 300~500줄. 보안 부채 전부 본인 부담 |

**Supabase는 DB 전용으로 두고 AS 역할은 분리한다.** 둘은 충돌하지 않는다.

## 4. 유료 전환 시 착수 순서

1. **spike부터.** [../spike/README.md](../spike/README.md) — 서버·터널·curl·판정 절차가 준비돼 있다. 확인할 것은 "쓰기 툴이 실제로 노출·호출되는가" 하나다
2. WorkOS 계정 생성 → AuthKit에서 DCR 토글, resource URL 등록
3. FastMCP에 `AuthKitProvider` 연결
4. 프로덕션 도메인 고정 후 배포
5. `interfaces/mcp_http.py` 추가 — `tool_registry.py`를 그대로 재사용한다

## 5. 구현 시 주의점

- **`base_url`은 실제 배포 URL과 정확히 일치해야 한다.** PRM의 resource 값이 곧 토큰의 `aud`다. Vercel 프리뷰 URL은 매번 바뀌므로 프로덕션 도메인을 고정할 것
- AuthKit 사용 시 클라이언트가 public client로 등록되도록 `token_endpoint_auth_method: "none"` 필요
- MCP 스펙 2025-11-25에서 **DCR이 SHOULD → MAY로 강등**되고 CIMD가 승격됐다. PRM(RFC 9728)과 RFC 8707은 여전히 MUST

## 6. 폴백 — Custom GPT Actions

MCP 커넥터가 막히면 이쪽이 남는다. **API Key 헤더 인증이 지원되므로 OAuth가 불필요하다** (구현 30분).

단 Custom GPTs 전반이 유지보수 모드로 들어가 Workspace Agents로 이전 중이라는 보도가 있다. 공식 sunset 날짜는 없다. 장기 의존은 피할 것.

`interfaces/rest_api.py`가 이 경로를 담당한다. FastAPI를 쓰면 OpenAPI 스펙이 자동 생성돼 추가 비용이 거의 없다.

---

## 검증 필요 항목

이 문서는 에이전트 웹 조사 기반이다. 착수 전 확인할 것:

- [ ] `AuthKitProvider`의 실제 존재와 API 형태 (FastMCP 공식 문서)
- [ ] WorkOS 무료 한도 (1M MAU로 조사됨)
- [ ] 쓰기 툴의 플랜별 게이팅 여부 — 가장 불확실한 항목
- [ ] ChatGPT 설정 화면의 현재 경로
