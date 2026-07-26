-- raw_postings 무한 증가 방지.
--
-- 전체 백필을 돌릴 때마다 같은 공고의 원본이 새 행으로 쌓인다.
-- 12,474건 × 약 2KB 이므로 백필 4회면 100MB — Supabase 무료 한도(500MB)에 닿는다.
--
-- raw 를 보관하는 목적은 '파서를 고친 뒤 재파싱' 하나다.
-- 그러려면 공고당 최신 1건이면 충분하다. 그보다 오래된 중복은 버린다.
--
-- 파싱에 실패한 행은 남긴다 — 그게 정확히 재처리 대상이다.

create or replace function prune_raw_postings()
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
  )
  delete from raw_postings
   where id in (select id from ranked where rn > 1);

  get diagnostics removed = row_count;
  return removed;
end;
$$;

revoke all on function prune_raw_postings() from public;
revoke all on function prune_raw_postings() from anon;
