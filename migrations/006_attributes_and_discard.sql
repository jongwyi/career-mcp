-- 1) prune 배치화  2) 사실 보류(discard)  3) 핵심 속성 테이블

-- ============================================================ 1. prune 배치화
--
-- 005 의 prune 은 62,000행 전체에 윈도우 함수를 걸어 문장 타임아웃(57014)이 났다.
-- 한 번에 지울 양을 제한하고, 호출측이 0이 될 때까지 반복한다.

create or replace function prune_raw_postings(batch_limit int default 2000)
returns int
language plpgsql
as $$
declare
  removed int;
begin
  with ranked as (
    select id,
           row_number() over (
             partition by source_id, external_id
             order by fetched_at desc, id desc
           ) as rn
      from raw_postings
     where parse_status = 'ok'
  ),
  victims as (
    select id from ranked where rn > 1 limit batch_limit
  )
  delete from raw_postings where id in (select id from victims);

  get diagnostics removed = row_count;
  return removed;
end;
$$;

revoke all on function prune_raw_postings(int) from public;
revoke all on function prune_raw_postings(int) from anon;
drop function if exists prune_raw_postings();

-- ============================================================ 2. 사실 보류
--
-- 임포트한 JSON 에 다른 사람의 정보나 사실과 다른 내용이 섞일 수 있다.
-- 지우지 않고 비활성화한다 — 나중에 "그때 뭘 뺐더라"를 되돌아볼 수 있어야 하고,
-- 잘못 뺐으면 되살릴 수 있어야 한다.
--
-- superseded_by 와 구분하는 이유: 대체(revise)는 '내용이 바뀐 것'이고
-- 보류(discard)는 '애초에 내 것이 아니거나 틀린 것'이다. 성격이 다르다.

alter table profile_facts
  add column discarded_at timestamptz,
  add column discard_reason text
    check (discard_reason in ('not_mine','incorrect','outdated','other'));

-- 보류된 사실은 유일성 제약에서 빠진다. 같은 내용을 나중에 다시 인정할 수 있어야 한다.
drop index if exists profile_facts_dedupe_active;
create unique index profile_facts_dedupe_active
  on profile_facts (dedupe_hash)
  where superseded_by is null and discarded_at is null;

drop index if exists profile_facts_kind_active;
create index profile_facts_kind_active
  on profile_facts (kind)
  where superseded_by is null and discarded_at is null;

-- ============================================================ 3. 핵심 속성
--
-- 모든 공공기관 인턴 공고가 연령(만 15~34세)을 요구하고, 학력·재학 여부·어학을
-- 조건으로 건다. 이건 '사실(fact)'이 아니라 '값'이다 — 하나뿐이고 갱신되며
-- 비어 있는지 아닌지가 중요하다. facts 로 표현하면 빠진 걸 알아챌 수 없다.

create table profile_attributes (
  key        text primary key,
  value      text not null check (length(btrim(value)) > 0),
  updated_at timestamptz not null default now()
);

alter table profile_attributes enable row level security;
