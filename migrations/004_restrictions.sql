-- 지원 자격 제한 태그.
--
-- 실측: 진행 중인 공공기관 인턴 공고 48건 중 26건(54%)이 장애인 전형·보훈
-- 제한경쟁·사회형평 채용 등 특정 자격자 전용이었다. 걸러내지 않으면
-- 추천 슬롯의 절반이 지원할 수 없는 공고로 찬다.
--
-- 버리지 않고 표시한다. 사용자가 실제로 해당될 수 있으므로
-- 기본 조회에서만 빼고, 몇 건을 뺐는지는 항상 보고한다.

alter table jobs
  add column restrictions text[] not null default '{}';

-- 기본 조회(제한 없는 인턴 + 신입 지원 가능)를 위한 인덱스.
create index jobs_open_unrestricted on jobs (deadline)
  where status = 'open'
    and restrictions = '{}'
    and employment_type = 'intern'
    and career_level in ('newgrad','both','unknown');

-- 제한 태그로 역조회 (사용자가 해당되는 경우)
create index jobs_restrictions on jobs using gin (restrictions);
