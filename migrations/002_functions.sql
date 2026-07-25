-- 원자적 연산을 위한 함수.
-- PostgREST 로는 두 번의 호출이 원자적이지 않아, 트랜잭션이 필요한 것만 여기 둔다.

-- ------------------------------------------------------------ supersede_fact
--
-- 기존 Fact 를 새 Fact 로 대체한다.
--   1) 대상이 활성인지 확인 (잠금)
--   2) 새 Fact 삽입
--   3) 기존 Fact 에 superseded_by 연결
--
-- 삽입을 먼저 하는 이유: superseded_by 가 새 행의 id 를 참조하는 FK 라서
-- 순서를 뒤집을 수 없다. 대신 그 사이 dedupe_hash 부분 유니크 인덱스와
-- 충돌할 수 있으므로, 내용이 실제로 바뀌었는지 먼저 검사한다.

create or replace function supersede_fact(p_fact_id bigint, p_new jsonb)
returns profile_facts
language plpgsql
as $$
declare
  v_old profile_facts;
  v_new profile_facts;
begin
  select * into v_old
    from profile_facts
   where id = p_fact_id and superseded_by is null
     for update;

  if not found then
    raise exception '대체할 수 없는 Fact 다 (없거나 이미 대체됨): id=%', p_fact_id
      using errcode = 'no_data_found';
  end if;

  if v_old.dedupe_hash = (p_new->>'dedupe_hash') then
    raise exception '내용이 바뀌지 않았다: id=%', p_fact_id
      using errcode = 'invalid_parameter_value';
  end if;

  insert into profile_facts
    (kind, content, evidence, tags, confidence, source, session_ref, dedupe_hash)
  values (
    p_new->>'kind',
    p_new->>'content',
    p_new->>'evidence',
    coalesce(
      (select array_agg(value::text) from jsonb_array_elements_text(p_new->'tags')),
      '{}'
    ),
    coalesce((p_new->>'confidence')::real, 0.7),
    p_new->>'source',
    p_new->>'session_ref',
    p_new->>'dedupe_hash'
  )
  returning * into v_new;

  update profile_facts set superseded_by = v_new.id where id = p_fact_id;

  return v_new;
end;
$$;

-- 확장(anon)은 프로필을 건드릴 수 없어야 한다.
-- SECURITY INVOKER 라 어차피 권한이 없지만, 호출 자체를 막아 둔다.
revoke all on function supersede_fact(bigint, jsonb) from public;
revoke all on function supersede_fact(bigint, jsonb) from anon;
