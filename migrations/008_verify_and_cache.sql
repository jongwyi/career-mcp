-- 1) 사실 확인(verify)  2) 평가 캐시

-- ============================================================ 1. 사실 확인
--
-- 임포트된 사실은 GPT 가 대화에서 추론한 것이라 과장이 섞인다.
-- 실제로 관찰된 예: "기획을 논의했다" → "기획에 참여했다".
-- confidence 는 GPT 가 스스로 매긴 값이라(59건 중 56건이 0.9) 신뢰할 수 없다.
--
-- 그래서 '사용자가 직접 확인했는가'를 별도로 둔다.
-- 매칭은 확인된 사실을 근거로 우선 쓰고, 미확인 사실은 표시한다 —
-- 자소서에 쓸 근거인데 과장이면 면접에서 무너진다.

alter table profile_facts
  add column verified_at timestamptz;

create index profile_facts_unverified
  on profile_facts (created_at desc)
  where verified_at is null and superseded_by is null and discarded_at is null;

-- ============================================================ 2. 평가 캐시
--
-- 매 실행마다 24건 전부를 다시 평가한다. 실제로 바뀌는 건 하루 1~2건이다.
-- 평가 당시의 공고 내용 해시와 프로필 시각을 남겨, 둘 다 그대로면 재평가를 건너뛴다.
--
-- 공고 해시는 저장하지 않고 매번 계산한다(도메인 속성). 컬럼을 늘리지 않기 위해서다.

alter table match_results
  add column job_hash text,
  add column profile_stamp timestamptz;

-- 캐시 조회용. 공고별 최신 평가를 빠르게 찾는다.
create index match_results_cache
  on match_results (job_id, id desc);
