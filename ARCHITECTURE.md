# 채용 매칭 시스템 아키텍처

> 상태: 설계 확정 (도메인·포트 구현 완료)
> 최종 수정: 2026-07-25 (rev.3 — Claude 단독 + 파일 임포트로 전환)

---

## 1. 목표

1. 강점·약점·경험을 축적하는 **영속 프로필 저장소**
2. 채용 공고를 자동 수집·정규화하는 **인제스천 파이프라인**
3. 프로필과 공고를 대조해 **근거와 gap을 함께 제시하는 매칭**

### 범위

**인턴 · 신입 채용에 한정한다.** 대외활동·공모전·서포터즈는 범위에서 제외했다 —
링커리어·캠퍼스픽·위비티·슈퍼루키·씽굿 전부 공식 API도 RSS도 없어
정당하게 확보할 소스가 존재하지 않는다 ([docs/SOURCES.md](docs/SOURCES.md) §5).
이 카테고리는 기존처럼 각 사이트에서 직접 본다.

### 대화 분리 / 지식 공유

| | GPT | Claude |
|---|---|---|
| 역할 | 자기 탐색 중심 (과거 대화 맥락 보유) | 현재 실무 중심 |
| 대화 이력 | 분리 유지 | 분리 유지 |
| 프로필 데이터 | **파일로 내보내 임포트** (단방향) | 직접 읽고 쓴다 |

ChatGPT Free 플랜에서는 커스텀 MCP 앱도 Custom GPT Actions도 사용할 수 없다.
따라서 GPT는 **툴 클라이언트가 아니라 입력 소스**로 취급한다.

- 임포트 형식: [docs/PROFILE_IMPORT_FORMAT.md](docs/PROFILE_IMPORT_FORMAT.md)
- 유료 전환 시 실시간 연동 설계: [docs/REMOTE_GPT_INTEGRATION.md](docs/REMOTE_GPT_INTEGRATION.md) (보류)

## 2. 제약 조건

| 제약 | 결정 |
|---|---|
| 상시 서버 없음 | 저장소=Supabase, 스케줄러=GitHub Actions, MCP=로컬 |
| 무료 플랜 유지 | 외부 LLM/임베딩 API 키 불필요 |
| ChatGPT Free | 원격 서버·OAuth 불필요. 파일 임포트로 대체 |
| 언어 | Python 3.12+ (코어), TypeScript (확장만) |

**rev.2 대비 사라진 것:** Vercel, FastAPI, OAuth, WorkOS, `access_tokens` 테이블, `interfaces/mcp_http.py`, `interfaces/rest_api.py`.
원격 연동이 빠지면서 시스템이 상당히 가벼워졌다.

## 3. 시스템 구성

```
┌──────────────────────┐
│  Claude              │        ┌──────────────────┐
│  Desktop / Code      │        │  ChatGPT (Free)  │
└──────────┬───────────┘        └────────┬─────────┘
           │ MCP (stdio)                 │ 파일 내보내기
           ▼                             │ (사용자가 직접)
┌──────────────────────┐                 │
│ interfaces/          │◄────────────────┘
│   mcp_stdio.py       │   profile-import-*.json
└──────────┬───────────┘
           │
┌──────────▼───────────┐
│ core/application     │
└──────────┬───────────┘
           ▼
┌──────────────────────────────┐
│  Supabase (무료)              │
│  Postgres 17 + pgvector       │
└──────▲──────────────▲────────┘
       │              │
┌──────┴────────┐  ┌──┴─────────────────┐
│ GitHub Actions│  │ Chrome Extension   │
│ 매일 06:00     │  │ (MV3)              │
│ 공식 API 수집  │  │ raw_postings 삽입만 │
└───────────────┘  └────────────────────┘
```

**핵심 원칙 2가지**

1. **챗봇은 실시간 수집을 하지 않는다.** 워커·확장이 정제해 둔 DB만 조회한다.
2. **수집 경로가 몇 개든 정규화 경로는 하나다.** 모든 입력은 `raw_postings`를 거쳐 동일한 파서를 탄다.

## 4. 전송 계층

| 전송 | 대상 | 위치 | 인증 |
|---|---|---|---|
| stdio MCP | Claude Desktop/Code | 로컬 | 불필요 |

전송이 하나뿐이지만 툴 선언은 `interfaces/tool_registry.py`에 따로 둔다.
[REMOTE_GPT_INTEGRATION.md](docs/REMOTE_GPT_INTEGRATION.md)의 HTTP 경로를 나중에 얹을 때
`mcp_http.py`가 이 레지스트리를 그대로 재사용하기 위해서다.
지금 분리해두는 비용은 거의 없고, 나중에 합치는 비용은 크다.

## 5. 데이터 모델

### 5.1 프로필 — append-only 이벤트 + 스냅샷

사실은 추가만 하고 수정은 supersede로 표현한다. 단일 클라이언트가 되었어도
이 구조를 유지하는 이유는 **동시성이 아니라 이력**이다 — 자기 이해는 시간이 지나며
바뀌고, 무엇이 언제 왜 바뀌었는지가 그 자체로 자소서 재료가 된다.

```sql
create table profile_facts (
  id            bigserial primary key,
  kind          text not null,      -- strength|weakness|skill|experience|preference|goal
  content       text not null,
  evidence      text,               -- 주장을 뒷받침하는 구체적 사례
  tags          text[] default '{}',
  confidence    real default 0.7,
  source        text not null,      -- claude|gpt_import|manual
  session_ref   text,
  dedupe_hash   text not null,      -- sha256(kind + 정규화된 content)
  created_at    timestamptz default now(),
  superseded_by bigint references profile_facts(id)
);

-- 활성 Fact 에 대해서만 유일성을 강제한다.
-- 대체된 Fact 와 충돌하지 않아야 같은 내용을 다시 인정하는 경우를 막지 않는다.
create unique index on profile_facts (dedupe_hash) where superseded_by is null;
create index on profile_facts (kind) where superseded_by is null;
create index on profile_facts (created_at desc);

create table profile_snapshot (
  id int primary key default 1,
  payload jsonb not null,
  fact_count int not null,
  updated_at timestamptz default now()
);
```

**`evidence`가 있는 이유.** 매칭 결과는 `{"jd_req": "...", "evidence_fact_id": 41}` 형태로
Fact를 역참조한다. 참조된 Fact에 근거가 없으면 왜 맞다고 보는지 설명할 수 없다.
근거 없는 강점은 매칭 점수는 올리지만 지원서에는 쓸 수 없다.

**`dedupe_hash`가 있는 이유.** GPT 임포트는 매번 전체를 다시 내보내는 방식이다.
사용자가 증분을 골라낼 필요 없이 중복이 DB 레벨에서 막힌다.

### 5.2 채용 공고

```sql
create table raw_postings (
  id             bigserial primary key,
  source_id      text not null,
  external_id    text not null,
  capture_method text not null,     -- api|worker_scrape|extension
  payload        jsonb not null,
  html_snapshot  text,              -- 확장 캡처 시 (최대 200KB)
  parse_status   text default 'pending',  -- pending|ok|failed
  parse_reason   text,
  fetched_at     timestamptz default now()
);
create index on raw_postings (parse_status) where parse_status <> 'ok';

create table jobs (
  id              bigserial primary key,
  source_id       text not null,
  external_id     text not null,
  title           text not null,
  company         text,
  url             text not null,
  employment_type text,             -- intern|newgrad|contract|activity|unknown
  location        text,
  deadline        date,
  jd_text         text,
  requirements    text[] default '{}',
  preferred       text[] default '{}',
  embedding       vector(1536),     -- v2용. v1은 NULL
  status          text default 'open',
  first_seen      timestamptz default now(),
  last_seen       timestamptz default now(),
  unique (source_id, external_id)
);
create index on jobs (status, deadline);
create index on jobs using gin (to_tsvector('simple', coalesce(jd_text,'')));
```

- `(source_id, external_id)` 유니크 제약이 중복 제거의 전부
- 마감 공고는 삭제하지 않고 `status='closed'`. 놓친 기회 회고가 가능해야 한다
- `parse_status='failed'`는 남겨둔다. 파서를 고친 뒤 재처리 대상이 된다

### 5.3 매칭 이력

```sql
create table match_runs (
  id bigserial primary key,
  criteria jsonb, fact_count int,
  created_at timestamptz default now()
);

create table match_results (
  id bigserial primary key,
  run_id bigint references match_runs(id),
  job_id bigint references jobs(id),
  score int,
  matched jsonb,   -- [{jd_req, evidence_fact_id}]
  gaps    jsonb    -- [{jd_req, severity, suggestion}]
);
```

## 6. 모듈 구조

```
career-mcp/
├── core/
│   ├── domain/                 ✅ 구현 완료 — 순수 로직, 외부 의존성 0
│   │   ├── profile.py          #   Fact, Snapshot, fact_hash, validate_supersede
│   │   ├── job.py              #   JobKey, RawPosting, JobPosting, ParseResult
│   │   └── match.py            #   MatchFilter, MatchCandidates, Evidence, Gap
│   ├── application/
│   │   ├── profile_service.py
│   │   ├── import_service.py   #   GPT 임포트 파일 → Fact
│   │   ├── job_query_service.py
│   │   ├── match_service.py
│   │   └── ingest_service.py   #   raw → parse → upsert (모든 경로 공용)
│   └── ports/                  ✅ 구현 완료 — 인터페이스만
│       ├── store.py            #   ProfileStore, RawStore, JobStore, MatchStore
│       └── source.py           #   PostingParser, PostingFetcher
├── adapters/
│   ├── store/supabase_store.py
│   └── sources/
│       ├── base.py             # rate limit, robots, 재시도
│       ├── worknet.py          # A등급
│       ├── saramin.py          # A등급
│       └── jobkorea_parser.py  # E등급 — parse 만, fetch 없음
├── interfaces/
│   ├── tool_registry.py        # 툴 선언 단일 소스
│   └── mcp_stdio.py            # Claude
├── worker/ingest.py            # GH Actions 진입점
├── extension/                  # Chrome MV3 (TypeScript)
├── migrations/001_init.sql
├── spike/                      # 일회용. 유료 전환 시 재사용
└── docs/
    ├── PROFILE_IMPORT_FORMAT.md
    └── REMOTE_GPT_INTEGRATION.md   (보류)
```

### 의존성 규칙 (강제)

```
interfaces ─┐
worker ─────┼──> application ──> domain
adapters ───┘         │
                      └──> ports (adapters가 구현)
extension ──직접──> Supabase raw_postings (RLS 제한)
```

- `domain`은 아무것도 import 하지 않는다
- `application`은 `ports` 인터페이스만 안다. Supabase의 존재를 모른다
- `interfaces/*`에는 비즈니스 로직을 두지 않는다 — 파싱·검증·위임만

실무에서 이 구조가 무너지는 지점은 언제나 "MCP 툴 핸들러에 SQL 한 줄만 넣자"다.

**포트를 fetch/parse로 나눈 이유.** 크롬 확장 소스는 가져오는 주체가 브라우저이지
서버가 아니라서 `PostingParser`만 구현한다. 하나의 `SourceAdapter`로 묶었다면
잡코리아 어댑터에 빈 `fetch()`를 두는 어색한 코드가 나왔을 것이다.

## 7. MCP 툴 명세

| 툴 | 입력 | 출력 |
|---|---|---|
| `profile_read` | `kinds?` | 스냅샷 |
| `profile_append` | `kind, content, evidence?, tags?, confidence?` | fact_id |
| `profile_revise` | `fact_id, new_content` | new_fact_id |
| `profile_diff` | `since?, source?` | 변경 목록 |
| `profile_import` | `file_path` | 신규/중복/오류 건수 |
| `jobs_search` | `keyword?, type?, location?, deadline_after?` | 공고 목록 |
| `jobs_match` | `limit?, filters?` | 후보 30~50건 + 프로필 요약 |
| `job_detail` | `job_id` | 전체 JD |
| `ingest_status` | — | 소스별 최종 수집 시각·건수 |

### 설계 노트

- **`jobs_match`는 순위를 매기지 않는다.** 후보군 + 프로필 스냅샷을 반환하고,
  순위·근거·gap 생성은 대화 중인 Claude가 한다. 외부 LLM 호출이 없어 비용이 0이다.
- **`ingest_status`는 필수다.** 추천이 언제 기준 데이터인지 모르면 시스템을 못 믿는다.
- **쓰기 결과는 항상 사용자에게 요약해 보여준다.** `profile_import`가 특히 그렇다 —
  무엇이 들어갔는지 확인할 수 없으면 프로필을 신뢰할 수 없게 된다.
- **출처 표기는 선택이 아니다.** `source_id='saramin'` 공고를 반환하는 툴
  (`jobs_search`·`jobs_match`·`job_detail`)은 응답에 "Powered by 취업 사람인"과
  사람인 제공 정보임을 함께 실어야 한다. API 이용 승인 조건이다 ([docs/SOURCES.md](docs/SOURCES.md) §2).
- 툴 description에 호출 조건을 구체적으로 쓴다. **모델이 툴을 안 부르는 것이 가장 흔한 실패 모드다.**

## 8. 수집 파이프라인

```
[A] 공식 API ────┐
[E] 크롬 확장 ───┼─> raw_postings ─> ingest_service.parse() ─> jobs
[B] 워커 스크랩 ─┘        (원본 보존)      (단일 정규화 경로)
```

### 소스 등급 (조사 완료 — 근거: [docs/SOURCES.md](docs/SOURCES.md))

| 등급 | 소스 | 방식 | 상태 |
|---|---|---|---|
| A | **재정경제부 공공기관 채용정보** (잡알리오) | 공식 API | ✅ 자동승인. 즉시 가능 |
| A | **사람인 오픈 API** | 공식 API | ✅ 개인 신청 가능 |
| E | 성균관대 (본인 계정 교내 공고) | 크롬 확장 | 6단계 |
| E | 기업 채용 홈페이지 등 임의 사이트 | 크롬 확장 | 6단계 |
| — | ~~워크넷 / 고용24~~ | — | ❌ 기업회원 전용. 개인 불가 |
| — | ~~잡코리아~~ | — | ❌ 약관·robots 충돌로 제외 |
| — | ~~링커리어, 슈퍼루키 등~~ | — | ❌ 범위 외 (대외활동) |

**A등급 2종의 예상 커버리지 (추정)**

| 범주 | 커버리지 |
|---|---|
| 인턴 | 60~75% |
| 신입 채용 | 70~80% |

가설("공식 API는 인턴에 얇다")은 **절반만 맞았다.** 인턴은 예상보다 잘 커버된다 —
재정경제부 API가 `청년인턴(채용형)`·`청년인턴(체험형)`을 독립 코드값으로 제공하고,
사람인이 `job_type=4,11`로 민간 인턴을 커버한다.
**공식 API 2개만으로 제품이 성립한다.**

남는 구멍은 스타트업 인턴(원티드·로켓펀치), 교내 공고, 기업 채용 홈페이지 직접 공고다.
E등급 확장이 이 틈을 메우지만 **A등급 없이는 성립하지 않는 보조 수단이다.**

### 어댑터 구현 시 반영

- 호출 한도는 병목이 아니다 (일 1회면 여유). **병목은 커버리지와 접근 자격이다**
- 사람인은 신입 필터를 요청 파라미터로 못 쓴다 → `parse()`에서 `experience-level.code`로 거른다
- 사람인은 **"Powered by 취업 사람인" 링크백이 의무**다 → 공고 표시 시 출처 명시
- 재정경제부 API는 코드 정의서 PDF로 코드값을 먼저 고정한다

**파서는 깨진다는 전제로 만든다.** `raw_postings`에 원본을 보관해 재파싱이 가능해야 하고,
한 소스의 파싱 실패가 다른 소스를 막아서는 안 된다.

## 9. 크롬 확장 설계

### 9.1 구조

```
extension/
├── manifest.json          # MV3
├── background.ts          # 큐잉, 배치 전송, 재시도
├── content/
│   ├── extractor.ts       # 3단 추출 전략
│   └── overlay.ts         # 저장 버튼 UI 주입
├── rules/                 # 사이트별 추출 규칙 (JSON)
│   ├── jobkorea.json
│   └── _generic.json
└── popup/                 # 설정, 수집 현황
```

**사이트 추가 = 코드가 아니라 `rules/*.json` 한 장 추가.**

### 9.2 3단 추출 전략 (fallback chain)

```
① JSON-LD        <script type="application/ld+json"> 의 schema.org/JobPosting
                 → 있으면 가장 정확하고 구조 변경에 강함
② CSS 규칙       rules/<domain>.json 의 셀렉터 맵
                 → 사이트별 수작업. 개편 시 깨짐
③ HTML 스냅샷    본문 영역 HTML을 그대로 전송 (최대 200KB)
                 → ①②가 실패해도 데이터는 보존. 서버에서 나중에 재파싱
```

③이 안전망이다. **추출에 실패해도 원본을 확보해 두면 페이지를 다시 방문하지 않고 파서를 고칠 수 있다.**

### 9.3 전송 경로 — rev.2에서 변경됨

rev.2는 "확장은 DB에 직접 쓰지 않고 REST를 거친다"였다. 그 REST가 Vercel에 있었고,
원격 서버가 사라지면서 경유할 곳이 없어졌다.

**변경: 확장이 Supabase에 직접 삽입한다.** RLS로 `raw_postings` INSERT만 허용한다.

정당화: 원본 적재에는 비즈니스 로직이 없다. 검증·정규화는 전부 워커의
`ingest_service.parse()`가 나중에 수행하고, 실패는 `parse_status='failed'`로 남는다.
경유 서버가 하던 일이 실제로는 없었다.

```sql
alter table raw_postings enable row level security;
create policy ext_insert on raw_postings
  for insert to anon with check (true);
-- profile_facts / jobs 등 나머지 테이블은 anon 에게 정책을 주지 않는다 → 접근 불가
```

**anon 키가 확장에 들어간다.** 이 키로 할 수 있는 최악은 `raw_postings`에 쓰레기 행을
넣는 것이고, 프로필은 읽을 수 없다. 확장은 스토어에 올리지 않고 언팩으로만 로드한다.

> 키를 확장 밖에 두고 싶으면 Supabase Edge Function(무료)에 디바이스 토큰 검증을
> 붙이는 강화 경로가 있다. 지금은 과설계로 판단해 보류한다.

### 9.4 대상 사이트

**잡코리아는 제외됐다.** robots.txt가 ClaudeBot·GPTBot을 명시적으로 차단하고(2026-04-01 갱신),
약관 제18조 ④가 "얻은 정보를 사전동의 없이 복사·복제하여 **사용하거나** 타인에게 제공"하는 것을
금지한다. 재배포 없는 개인 사용이라도 문구상 걸린다.

**1순위 대상: 성균관대 교내 공고.** 본인 학교 계정으로 열람하는, 본인에게 제공된 정보다.
`external_id`는 URL 쿼리스트링에서 뽑는다. 로그인 세션이 필요하면 확장이 이미
브라우저 안에 있으므로 별도 처리가 필요 없다 — **이게 서버 워커 대비 확장의 실질적 이점이다.**

**2순위: 기업 채용 홈페이지 직접 공고.** 어떤 API에도 없는 물량이고,
JSON-LD `JobPosting`을 제공하는 곳이 많아 `_generic.json`이 그대로 처리한다.

새 사이트를 추가할 때는 **먼저 robots.txt와 약관을 확인한다.**
확인 결과를 [docs/SOURCES.md](docs/SOURCES.md)에 기록한 뒤 `rules/`에 규칙을 추가한다.

**공통 규칙:** 자동 페이지 순회를 넣지 않는다. 사용자가 실제로 보는 화면만 캡처한다.

**`external_id`를 URL 경로에서 뽑는 게 중요하다.** DOM보다 훨씬 덜 변하고,
중복 제거 키가 안정적이어야 파이프라인 전체가 안정적이다.

**캡처 모드:** 패시브(상세 페이지 방문 시 자동) / 목록(보이는 카드 일괄) / 버튼(수동).
**자동 페이지 순회는 넣지 않는다.** 사용자가 실제로 보는 화면만 캡처한다 —
이게 서버 크롤링과 성격을 구분 짓는 조건이다.

**흐름**

```
1. content script 가 URL 을 rules/ 와 매칭
2. 추출 시도 ① → ② → ③
3. external_id 로 로컬 dedup (chrome.storage.local, TTL 24h)
4. background 큐에 적재
5. 10건 또는 30초마다 Supabase 에 배치 INSERT
6. 실패 시 큐를 유지하고 지수 백오프 재시도 (브라우저를 닫아도 유실 없음)
```

**권한 최소화:** `<all_urls>`를 요구하지 않는다. 사이트 추가 시
`optional_host_permissions`로 사용자가 개별 승인한다.

## 10. 매칭 파이프라인

```
① 규칙 필터 (SQL)   status/deadline/type/location + FTS 키워드
                    수백 건 → 30~50건
② [v2] 벡터 검색    pgvector 코사인 유사도
③ Claude 리랭크     대화 중 수행
```

③ 출력 형태:

```json
{
  "job_id": 812, "score": 82,
  "matched": [{"jd_req": "Flutter 앱 개발 경험", "evidence_fact_id": 41}],
  "gaps": [{"jd_req": "REST API 설계 경험", "severity": "medium",
            "suggestion": "book_api_test 프로젝트를 API 설계 관점으로 재정리"}]
}
```

## 11. 보안

| 항목 | 처리 |
|---|---|
| Supabase 서비스 키 | 로컬 `.env` + GH Secrets. 확장에는 절대 넣지 않음 |
| Supabase anon 키 | 확장에만. RLS로 `raw_postings` INSERT 한정 |
| RLS | **주 통제 수단.** 모든 테이블에 활성화, anon 은 명시된 것만 |
| 저장소 | 비공개 필수 |
| 사이트 자격증명 | 저장하지 않음 |
| 프로필 데이터 | git 커밋 금지. 임포트 JSON 파일도 `.gitignore` |

원격 엔드포인트가 없어 공격면이 rev.2보다 크게 줄었다. 남은 노출은 anon 키 하나뿐이다.

## 12. 비용

| 항목 | 플랜 | 월 비용 |
|---|---|---|
| Supabase | Free (DB 500MB) | ₩0 |
| GitHub Actions | 비공개 2,000분 중 ~150분 | ₩0 |
| MCP 서버 | 로컬 | ₩0 |
| Chrome 확장 | 언팩 로드 | ₩0 |
| LLM / 임베딩 | 미사용 | ₩0 |

**주의:** Supabase 무료 프로젝트는 7일 무활동 시 일시정지된다. 매일 도는 수집 크론이 이를 방지한다.
**주의:** GitHub Actions 스케줄은 저장소가 60일간 활동이 없으면 자동 비활성화된다.

## 13. 로드맵

| 단계 | 범위 | 예상 | 산출물 |
|---|---|---|---|
| ~~0~~ | ~~ChatGPT 연동 spike~~ | — | **보류** (Free 플랜) |
| **1** | Supabase 프로젝트 + 스키마 마이그레이션 | 0.5일 | DB 준비 |
| **2** | application + supabase_store + tool_registry + stdio MCP | 3~4일 | **Claude에서 프로필 동작** |
| **3** | `profile_import` + GPT 내보내기 프롬프트 검증 | 1일 | **GPT 대화 내용이 DB로 들어옴** |
| **4a** | 재정경제부 API 어댑터 + GH Actions cron | 2~3일 | 공공기관 인턴이 쌓임 |
| **4b** | 사람인 어댑터 (신청·승인 선행) | 1~2일 | 민간 인턴 추가 |
| **5** | `jobs_search` / `jobs_match` / `job_detail` | 2~3일 | 추천 + gap 분석 |
| **6** | 크롬 확장 (성균관대 우선) | 3~4일 | 확장 캡처 연동 |
| **7** | 마감 알림, 지원 이력, 벡터 검색 | — | |

✅ **완료:** `core/domain` 3파일, `core/ports` 2파일 — import·불변식 검증 통과

2·3단계만 끝나면 **"내가 나에 대해 알아낸 것이 한 곳에 쌓이는"** 상태가 된다.
채용 수집이 하나도 없어도 그 자체로 쓸모가 있다.

**4a를 4b보다 먼저 두는 이유:** 재정경제부 API는 자동승인이라 대기가 없고,
사람인은 심사에 며칠 걸린다. 4b 신청서는 4a 착수와 동시에 넣어두면 대기가 겹치지 않는다.

## 14. 미결정 사항

1. **프로필 kind 분류 체계** — 2단계에서 실사용하며 확정
2. **원티드·로켓펀치의 확장 수집 가능 여부** — 6단계 착수 시 약관·robots 확인
3. **벡터 검색 도입 시점** — 공고 2,000건 초과 시

### 결정된 것

- ~~잡코리아 확장 대상 유지~~ → **제외** (약관·robots 충돌)
- ~~대외활동 범위~~ → **범위 외** (정당한 소스 부재). 인턴·신입에 집중
