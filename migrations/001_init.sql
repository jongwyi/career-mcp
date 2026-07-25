-- 채용 매칭 시스템 초기 스키마
-- Supabase (Postgres 17) · Supabase SQL Editor 에서 실행
--
-- CHECK 제약은 core/domain 의 StrEnum 과 값이 일치한다.
-- 어댑터가 잘못된 값을 넣으면 조용히 통과하지 않고 여기서 걸린다.

create extension if not exists vector;

-- ============================================================ 프로필

create table profile_facts (
  id            bigserial primary key,
  kind          text not null
                check (kind in ('strength','weakness','skill',
                                'experience','preference','goal')),
  content       text not null check (length(btrim(content)) > 0),
  evidence      text,                        -- 주장을 뒷받침하는 구체적 사례
  tags          text[] not null default '{}',
  confidence    real not null default 0.7 check (confidence between 0 and 1),
  source        text not null
                check (source in ('claude','gpt_import','manual')),
  session_ref   text,
  dedupe_hash   text not null,               -- sha256(kind + 정규화된 content)
  created_at    timestamptz not null default now(),
  superseded_by bigint references profile_facts(id)
);

-- 활성 Fact 에 대해서만 유일성을 강제한다.
-- 대체된 Fact 와 충돌하지 않아야, 한번 철회한 내용을 다시 인정하는 경우를 막지 않는다.
create unique index profile_facts_dedupe_active
  on profile_facts (dedupe_hash) where superseded_by is null;
create index profile_facts_kind_active
  on profile_facts (kind) where superseded_by is null;
create index profile_facts_created_at on profile_facts (created_at desc);
create index profile_facts_source on profile_facts (source);

create table profile_snapshot (
  id         int primary key default 1 check (id = 1),   -- 단일 행
  payload    jsonb not null,
  fact_count int not null,
  updated_at timestamptz not null default now()
);

-- ============================================================ 채용 공고

create table raw_postings (
  id             bigserial primary key,
  source_id      text not null,
  external_id    text not null,
  capture_method text not null
                 check (capture_method in ('api','worker_scrape','extension')),
  payload        jsonb not null,
  html_snapshot  text,                        -- 확장 캡처 시. 최대 200KB
  parse_status   text not null default 'pending'
                 check (parse_status in ('pending','ok','failed')),
  parse_reason   text,
  fetched_at     timestamptz not null default now()
);

-- 파서를 고친 뒤 재처리할 대상만 빠르게 찾는다.
create index raw_postings_unparsed
  on raw_postings (fetched_at) where parse_status <> 'ok';
create index raw_postings_source on raw_postings (source_id, external_id);

create table jobs (
  id              bigserial primary key,
  source_id       text not null,
  external_id     text not null,
  title           text not null check (length(btrim(title)) > 0),
  url             text not null check (length(btrim(url)) > 0),
  company         text,
  employment_type text not null default 'unknown'
                  check (employment_type in ('intern','newgrad','contract',
                                             'activity','unknown')),
  location        text,
  deadline        date,
  jd_text         text,
  requirements    text[] not null default '{}',
  preferred       text[] not null default '{}',
  embedding       vector(1536),                -- v2용. v1은 NULL
  status          text not null default 'open'
                  check (status in ('open','closed')),
  first_seen      timestamptz not null default now(),
  last_seen       timestamptz not null default now(),
  unique (source_id, external_id)              -- 중복 제거의 전부
);

create index jobs_open_deadline on jobs (deadline) where status = 'open';
create index jobs_employment_type on jobs (employment_type) where status = 'open';
create index jobs_fts on jobs
  using gin (to_tsvector('simple',
             coalesce(title,'') || ' ' || coalesce(jd_text,'')));

-- ============================================================ 매칭 이력

create table match_runs (
  id         bigserial primary key,
  criteria   jsonb,
  fact_count int,
  created_at timestamptz not null default now()
);

create table match_results (
  id      bigserial primary key,
  run_id  bigint not null references match_runs(id) on delete cascade,
  job_id  bigint not null references jobs(id) on delete cascade,
  score   int not null check (score between 0 and 100),
  matched jsonb not null default '[]',   -- [{jd_req, evidence_fact_id}]
  gaps    jsonb not null default '[]'    -- [{jd_req, severity, suggestion}]
);

create index match_results_run on match_results (run_id, score desc);
create index match_results_job on match_results (job_id);

-- ============================================================ RLS
--
-- 주 통제 수단이다. service_role 키(로컬 MCP·GH Actions 워커)는 RLS 를 우회한다.
-- anon 키(크롬 확장)는 아래 정책으로 허용된 것만 할 수 있다.

alter table profile_facts    enable row level security;
alter table profile_snapshot enable row level security;
alter table raw_postings     enable row level security;
alter table jobs             enable row level security;
alter table match_runs       enable row level security;
alter table match_results    enable row level security;

-- 확장은 원본 적재만 한다. 읽기도, 수정도, 삭제도 못 한다.
create policy extension_insert_raw on raw_postings
  for insert to anon with check (true);

-- 나머지 테이블에는 anon 정책을 만들지 않는다 → 접근 불가.
-- 특히 profile_facts 는 anon 이 절대 읽을 수 없어야 한다.

-- ------------------------------------------------------------ GRANT
--
-- 이중 방어. Supabase 는 public 스키마 새 테이블에 anon 권한을 기본 부여하므로,
-- 명시적으로 회수한 뒤 필요한 것만 되돌려준다.
-- RLS 가 실수로 꺼져도 GRANT 단에서 한 번 더 막힌다.

revoke all on all tables in schema public from anon;
revoke all on all sequences in schema public from anon;

grant usage on schema public to anon;
grant insert on raw_postings to anon;
-- bigserial INSERT 에는 시퀀스 USAGE 가 필요하다. 없으면 정책을 통과해도 실패한다.
grant usage on sequence raw_postings_id_seq to anon;
