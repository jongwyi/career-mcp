# 채용 데이터 소스 조사

> 조사 시점: 2026-07-25 · 개인 비영리 프로젝트 기준
> 요약은 [ARCHITECTURE.md §8](../ARCHITECTURE.md)에 있다. 이 문서는 근거와 세부 사항.

---

## 결론 먼저

개인 자격으로 확보 가능한 무료 공식 API는 **사실상 2개**다.

| 순위 | 소스 | 상태 |
|---|---|---|
| 1 | **재정경제부 공공기관 채용정보** (잡알리오) | 자동승인. **오늘 바로 시작 가능** |
| 2 | **사람인 오픈 API** | 개인 신청 가능. 승인 며칠 |

이 조합의 예상 커버리지 (추정치):

| 범주 | 커버리지 |
|---|---|
| 인턴 | 60~75% |
| 신입 채용 | 70~80% |
| **대외활동·공모전·서포터즈** | **0%** |

**인턴은 가설보다 잘 커버되고, 대외활동은 통째로 비어 있다.**

---

## 1. 재정경제부 공공기관 채용정보 ⭐ 1순위

https://www.data.go.kr/data/15125273/openapi.do

| 항목 | 값 |
|---|---|
| 유형 | REST (LINK 아님 → data.go.kr에서 바로 승인) |
| 승인 | **개발계정 자동승인** |
| 한도 | 1,000건/일 |
| 포맷 | JSON + XML |
| 라이선스 | **이용허락범위 제한 없음** |

엔드포인트 (존재 확인됨, 키 없이 401 반환):
```
https://apis.data.go.kr/1051000/recruitment/list
https://apis.data.go.kr/1051000/recruitment/detail
```

**인턴 필터가 API 레벨에 실재한다.** 이게 이 소스를 1순위로 만드는 이유다.

- 고용형태: 정규직 / 비정규직 / 무기계약직 / **청년인턴(채용형)** / **청년인턴(체험형)**
- 채용구분: **신입** / 경력 / 신입+경력 / 외국인전형

파라미터명은 `hireTypeLst`, `recrutSe`, `workRgnLst`, `acbgCondLst`, `ncsCdLst`로 확인됐다.
**정확한 코드값은 data.go.kr 첨부 PDF(`MOEF_NKOD_DB_05_코드 정의서_v1.2`)로 확정해야 한다.**

커버리지: 370여 개 공공기관 수시공시 전수. 공공기관 인턴은 사실상 완전 커버.

## 2. 사람인 오픈 API — 2순위

https://oapi.saramin.co.kr/

| 항목 | 값 |
|---|---|
| 엔드포인트 | `https://oapi.saramin.co.kr/job-search` (GET, `access-key`) |
| 한도 | **500회/일**, 호출당 최대 110건 |
| 포맷 | JSON (`Accept: application/json`) + XML |
| 신청 | https://oapi.saramin.co.kr/join |

**개인 신청 가능하다.** 신청 폼에 "회사명/**학교명**, 부서명/**전공명**" 입력란이 있다.
"이용목적 50자 이상" 기술 필요.

**인턴 필터: 가능.** `job_type` 코드 — `4 = 인턴직`, `11 = 인턴직(정규직 전환가능)`, `12 = 교육생`

**신입 필터: 요청 파라미터로는 불가.** 경력 조건 요청 파라미터가 없다.
응답의 `experience-level.code`(1=신입, 2=경력, 3=신입/경력, 0=경력무관)를 받아
**클라이언트 측에서 걸러야 한다.** → 어댑터 설계에 반영할 것.

**의무 사항:**
- **"Powered by 취업 사람인" 링크백 필수**, 사람인 제공 정보임을 명시
- 재판매·이용요금 발생 금지
- 승인 유효기간 1년 (갱신 필요)
- 베타 서비스로 인터페이스 변경 가능성 명시됨

## 3. 워크넷 / 고용24 — ❌ 개인 접근 불가

https://www.data.go.kr/data/3038225/openapi.do

파라미터 30종 이상에 국내 최대 공공 채용 DB지만 **개인은 인증키를 받을 수 없다.**

work24 공식 안내 원문:
> "OPEN-API는 고용 24 **기업회원 전용** 서비스입니다."
> "담당자 심사가 진행되며 심사가 완료되면 인증키가 발급"
> "인증키는 타 기관에 양도할 수 없습니다."

기업회원 가입에 **사업자등록번호가 필요하다.** 추가 장애물:
- API 유형이 `LINK` — data.go.kr이 아니라 고용24에서 별도 발급
- 라이선스 CC-BY-NC-**ND** (변경금지) → 가공에 제약
- 응답 XML 전용
- 일일 한도 미공개

**이게 가장 아픈 구멍이다.** 설계에서 제외한다.

부속 API인 공채속보(15027228)는 필터가 거의 없어 전건 수집 후 클라이언트 필터가 필요하고,
15031951은 이름과 달리 공고가 아니라 **공채기업 정보**(기업개요·인재상·복리후생)다.

## 4. 잡코리아 — ⚠️ 약관·robots 정면 충돌

https://www.jobkorea.co.kr/service/api

API가 존재하지만 신청 자격 원문:
> "**공공기관 또는 학교를 대상으로** 제공하는 서비스입니다.
> (개인, 일반 기업 등은 내부 검토 후 제공이 불가할 수 있습니다)"

**robots.txt가 ClaudeBot·GPTBot을 명시적으로 차단한다** (`Last updated: 2026-04-01`):
> `# Policy: Restrict AI/LLM crawlers while allowing search engine indexing of public pages.`
> `User-agent: ClaudeBot … Disallow: /`

CCBot, Diffbot, DeepSeek, Amazonbot은 화이트리스트 없이 전면 차단.

**개인회원 약관 제18조 ④:**
> "회원은 서비스를 이용하여 얻은 정보를 회사의 사전동의 없이 **복사, 복제**, 번역, 출판,
> 방송 기타의 방법으로 **사용하거나** 이를 타인에게 제공할 수 없다."

"타인에게 제공"뿐 아니라 "**복사·복제하여 사용**"까지 금지 대상이다.
개인 사용·재배포 없음이어도 문구상 걸린다. 크롤링 소송 이력이 있는 사이트이기도 하다.

**→ 크롬 확장 대상으로 유지할지는 사용자의 리스크 수용 결정 사항.**

## 5. 대외활동·공모전 전문 사이트 — 전멸

| 사이트 | 공식 API | RSS | 약관 |
|---|---|---|---|
| 링커리어 | 없음 | 없음 (`/rss`, `/feed`, `/sitemap.xml` 404) | 크롤링 명시 금지는 **STEM 기출 한정**. robots.txt `Allow: /` |
| 캠퍼스픽 | 없음 | 없음 | **가장 강력한 명시적 금지 + 실제 403** |
| 위비티 | 없음 | 없음 | 상업적 이용 금지. robots.txt `Allow: /` + GPTBot `Crawl-delay: 3` |
| 슈퍼루키 | 없음 | 없음 | 복제·제공 금지 |
| 씽굿 | 없음 | 없음 | 영리목적 이용 금지 |
| 독취사/스펙업 (네이버 카페) | 없음 | 없음 | robots.txt 전면 차단 + AI 금지 명문 |

**캠퍼스픽** (제12조 금지행위) — 조사 대상 중 가장 명시적:
> "프로그램, 스크립트, 봇을 이용한 서비스 접근 등 사람이 아닌 컴퓨팅 시스템을 통한 서비스 접근 행위"
> "API 직접 호출, 유저 에이전트 조작, 패킷 캡처, 비정상적인 반복 조회 및 요청 등 허가하지 않은 방식의 서비스 이용 행위"

제9조에서 **DB제작자 권리를 명시적으로 주장**한다. 헤드리스 브라우저 기본 UA에 실제로 403을 반환한다.

**링커리어** (제16조)는 상대적으로 약하다 — "자동 접속 프로그램 등으로 **서버에 부하를 일으켜**
정상적인 서비스를 방해하는 행위"로, 부하 유발이 조건이다. 크롤링·스크래핑 명시 조항은
STEM 기출콘텐츠에 한정되고 대외활동 공고에는 직접 문구가 없다. robots.txt는 개방적.

**위비티**는 "가공, 판매하는 행위 등 **상업적** 이용" 금지로, 개인 비영리와는 결이 다르다.

## 6. 기타

- **원티드 OpenAPI** — 존재하나 파트너 심사제. 개인 통과 가능성 낮음
- **온통청년 API** — **정책 정보만.** "청년인턴 지원사업이라는 제도가 있다"는 나오지만
  "○○공단이 체험형 인턴 5명을 8/15까지 모집한다"는 나오지 않는다. 공고가 아니다
- **청년일경험 통합플랫폼 / 청년몽땅정보통** — 공개 API 없음 (URL에 `/api/`가 있으나 HTML 목록)
- **서울 일자리플러스센터 (OA-13341)** — 신청 난이도 낮음. 인턴 코드는 존재하나 값 불확실. 서울 한정
- **인크루트 / 잡플래닛** — 공개 문서 부재

---

## 어댑터 설계에 반영할 것

1. **호출 한도는 병목이 아니다.** 일 1회 수집이면 사람인 500회·공공데이터 1,000건 모두 여유롭다.
   **병목은 커버리지와 접근 자격이다.**
2. 사람인은 신입 필터를 클라이언트에서 처리해야 한다 → `saramin.py`의 `parse()`에서 걸러낸다
3. 사람인 링크백 의무 → 공고 표시 시 출처 명시 필요
4. 재정경제부 API는 코드 정의서 PDF를 먼저 받아 코드값을 상수로 고정한다

## 근거 URL

**공공**
- https://www.data.go.kr/data/15125273/openapi.do
- https://opendata.alio.go.kr/new/odaApiMng/recrutInquiryList.do
- https://www.data.go.kr/data/3038225/openapi.do
- https://www.work24.go.kr/cm/e/a/0110/selectOpenApiIntro.do
- https://www.data.go.kr/data/15143273/openapi.do

**민간**
- https://oapi.saramin.co.kr/ · /guide/code-table1 · /join
- https://www.jobkorea.co.kr/service/api
- https://openapi.wanted.jobs/

**약관 / robots.txt**
- https://www.jobkorea.co.kr/service/ProvisionGG · https://www.jobkorea.co.kr/robots.txt
- https://www.campuspick.com/page/userserviceagreement
- https://linkareer.com/terms · https://linkareer.com/robots.txt
- https://www.wevity.com/?c=intro&s=4
- https://www.superookie.com/legal/terms
- https://www.saramin.co.kr/robots.txt · https://cafe.naver.com/robots.txt
