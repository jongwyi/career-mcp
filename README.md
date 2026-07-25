# career-mcp

대학생 개인이 취업 준비에 쓰는 **인턴·신입 채용 매칭 도구**입니다.

AI 챗봇(Claude)과의 대화로 자신의 강점·약점·경험을 축적하고,
공식 API로 수집한 채용 공고와 대조해 **지원 가능한 공고와 부족한 자격 요건**을 찾습니다.

개인 비영리 프로젝트이며, 수집한 데이터는 본인 데이터베이스에만 저장합니다.
제3자에게 제공하거나 재판매하지 않습니다.

---

## 무엇을 하나

1. **프로필 축적** — 대화에서 드러난 사실을 근거(evidence)와 함께 기록합니다.
   수정은 덮어쓰기가 아니라 이력을 남기는 방식이라, 자기 이해가 어떻게 변해왔는지 추적됩니다.
2. **공고 수집** — 하루 1회, 공식 오픈 API로 인턴·신입 공고를 가져옵니다.
3. **매칭** — 공고의 요구사항과 프로필을 대조해 근거와 gap을 함께 제시합니다.

```json
{
  "job_id": 812, "score": 82,
  "matched": [{"jd_req": "Flutter 앱 개발 경험", "evidence_fact_id": 41}],
  "gaps": [{"jd_req": "REST API 설계 경험", "severity": "medium",
            "suggestion": "기존 프로젝트를 API 설계 관점으로 재정리"}]
}
```

단순 점수가 아니라 **왜 맞다고 보는지**를 프로필의 특정 사실로 역참조합니다.
근거 없는 매칭은 지원서에 쓸 수 없기 때문입니다.

## 데이터 출처

| 소스 | 방식 |
|---|---|
| 재정경제부 공공기관 채용정보 (잡알리오) | 공공데이터포털 오픈 API |
| 사람인 | 사람인 오픈 API |

### 출처 표기

- **사람인 제공 공고를 표시할 때는 "Powered by 취업 사람인" 링크백과
  사람인 제공 정보임을 함께 표시합니다.** API 이용 조건에 따른 것으로,
  공고를 반환하는 모든 도구(`jobs_search`, `jobs_match`, `job_detail`) 응답에 포함됩니다.
- 수집은 **1일 1회**이며 각 API의 일일 호출 한도 내에서만 사용합니다.
- 공식 API가 없거나 이용약관이 자동 수집을 금지하는 사이트는 수집하지 않습니다.
  판단 근거는 [docs/SOURCES.md](docs/SOURCES.md)에 기록합니다.

## 범위

**인턴·신입 채용에 한정합니다.** 대외활동·공모전은 정당하게 확보할 수 있는
공식 소스가 존재하지 않아 범위에서 제외했습니다.

## 구조

```
Claude Desktop / Code
   │ MCP (stdio, 로컬)
   ▼
core/application ──> core/domain     순수 로직, 외부 의존성 0
   │      └────────> core/ports      인터페이스
   ▼
Supabase (Postgres)
   ▲
   ├── GitHub Actions (일 1회 공식 API 수집)
   └── Chrome Extension (사용자가 직접 연 페이지만 캡처)
```

상시 서버가 없습니다. 저장소는 Supabase, 스케줄러는 GitHub Actions,
MCP 서버는 사용자 로컬에서 동작합니다.

- 설계: [ARCHITECTURE.md](ARCHITECTURE.md)
- 소스 조사: [docs/SOURCES.md](docs/SOURCES.md)
- 프로필 임포트 형식: [docs/PROFILE_IMPORT_FORMAT.md](docs/PROFILE_IMPORT_FORMAT.md)

## 상태

개발 중입니다.

| | |
|---|---|
| ✅ | `core/domain`, `core/ports`, `core/application` |
| ✅ | DB 스키마 (`migrations/001_init.sql`) |
| 🚧 | Supabase 어댑터, MCP 서버 |
| 📋 | 수집 어댑터, 매칭, 크롬 확장 |

## 기술

Python 3.12+ · FastMCP · Supabase (Postgres + pgvector) · GitHub Actions

---

개인 학습·취업 준비 목적의 비영리 프로젝트입니다.
