-- 고용형태와 채용구분을 분리한다.
--
-- 001 의 employment_type 은 '인턴/신입/계약직'을 한 컬럼에 뭉쳐 놨는데,
-- 실제 소스(재정경제부 API 의 hireTypeLst / recrutSe, 사람인의 job_type /
-- experience-level)는 둘을 별개 필드로 준다. 하나로 합치면
-- '정규직 신입'과 '계약직 신입'이 구분되지 않는다.
--
-- jobs 가 비어 있는 시점이라 데이터 마이그레이션이 필요 없다.

alter table jobs drop constraint if exists jobs_employment_type_check;

alter table jobs
  alter column employment_type set default 'unknown',
  add constraint jobs_employment_type_check
    check (employment_type in ('intern','fulltime','contract','unknown'));

alter table jobs
  add column career_level text not null default 'unknown'
    check (career_level in ('newgrad','experienced','both','unknown')),
  add column education text,        -- 학력 조건 (예: 대졸(4년),석사)
  add column job_field text,        -- NCS 직무분야
  add column headcount int;

-- 인턴 + 신입 지원 가능 공고가 가장 흔한 조회다.
create index jobs_intern_newgrad on jobs (deadline)
  where status = 'open'
    and employment_type = 'intern'
    and career_level in ('newgrad','both','unknown');
