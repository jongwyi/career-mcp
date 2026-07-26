-- 지원 상태 추적 + 매칭 이력
--
-- 문제 1: 매번 같은 24건이 다시 올라온다. 이미 거른 것, 지원한 것을 구분할 곳이 없다.
-- 문제 2: 점수가 매번 달라진다. Claude 가 매번 새로 판단하므로
--         어제 80점이 오늘 65점일 수 있고, 비교할 기록이 없다.

-- ============================================================ 지원 상태

create table job_interest (
  job_id     bigint primary key references jobs(id) on delete cascade,
  status     text not null
             check (status in ('saved','applied','not_interested','rejected','accepted')),
  note       text,
  updated_at timestamptz not null default now()
);

create index job_interest_status on job_interest (status, updated_at desc);

alter table job_interest enable row level security;

-- ============================================================ 매칭 이력
--
-- match_runs / match_results 는 001 에서 만들었지만 쓰이지 않고 있었다.
-- 조회 편의를 위한 인덱스와, 공고별 최신 점수를 뽑는 뷰를 추가한다.

create index if not exists match_results_job_score
  on match_results (job_id, id desc);

alter table match_runs enable row level security;
alter table match_results enable row level security;

-- 공고별 가장 최근 평가. "이전 추천을 한눈에" 의 재료다.
create or replace view latest_match_scores as
select distinct on (r.job_id)
       r.job_id, r.score, r.matched, r.gaps,
       n.created_at as evaluated_at, n.id as run_id
  from match_results r
  join match_runs n on n.id = r.run_id
 order by r.job_id, n.created_at desc, r.id desc;
