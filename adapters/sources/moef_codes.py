"""재정경제부 공공기관 채용정보 API 코드값.

출처: docs/MOEF_NKOD_DB_05_코드 정의서_v1.2 [배포용].pdf
추측하지 않고 정의서 값을 그대로 옮긴다.
"""

from __future__ import annotations

from core.domain.job import CareerLevel, EmploymentType

# ---------------------------------------------------------------- 고용형태 R1000

HIRE_FULLTIME = "R1010"  # 정규직
HIRE_CONTRACT = "R1020"  # 계약직
HIRE_PERMANENT_CONTRACT = "R1030"  # 무기계약직
HIRE_NONREGULAR = "R1040"  # 비정규직
HIRE_INTERN = "R1050"  # 청년인턴
HIRE_INTERN_EXPERIENCE = "R1060"  # 청년인턴(체험형)
HIRE_INTERN_HIRING = "R1070"  # 청년인턴(채용형)

#: 인턴 계열 전체. 수집 필터의 핵심.
INTERN_CODES = (HIRE_INTERN, HIRE_INTERN_EXPERIENCE, HIRE_INTERN_HIRING)

EMPLOYMENT_TYPE_BY_CODE = {
    HIRE_FULLTIME: EmploymentType.FULLTIME,
    HIRE_CONTRACT: EmploymentType.CONTRACT,
    HIRE_PERMANENT_CONTRACT: EmploymentType.CONTRACT,
    HIRE_NONREGULAR: EmploymentType.CONTRACT,
    HIRE_INTERN: EmploymentType.INTERN,
    HIRE_INTERN_EXPERIENCE: EmploymentType.INTERN,
    HIRE_INTERN_HIRING: EmploymentType.INTERN,
}

# ---------------------------------------------------------------- 채용구분 R2000

RECRUIT_NEWGRAD = "R2010"  # 신입
RECRUIT_EXPERIENCED = "R2020"  # 경력
RECRUIT_BOTH = "R2030"  # 신입+경력
RECRUIT_FOREIGN = "R2040"  # 외국인 전형

#: 신입이 지원 가능한 채용구분.
NEWGRAD_CODES = (RECRUIT_NEWGRAD, RECRUIT_BOTH)

CAREER_LEVEL_BY_CODE = {
    RECRUIT_NEWGRAD: CareerLevel.NEWGRAD,
    RECRUIT_EXPERIENCED: CareerLevel.EXPERIENCED,
    RECRUIT_BOTH: CareerLevel.BOTH,
    RECRUIT_FOREIGN: CareerLevel.UNKNOWN,
}

# ---------------------------------------------------------------- 근무지 R3000

REGION_BY_CODE = {
    "R3010": "서울", "R3011": "인천", "R3012": "대전", "R3013": "대구",
    "R3014": "부산", "R3015": "광주", "R3016": "울산", "R3017": "경기",
    "R3018": "강원", "R3019": "충남", "R3020": "충북", "R3021": "경북",
    "R3022": "경남", "R3023": "전남", "R3024": "전북", "R3025": "제주",
    "R3026": "세종", "R3030": "해외",
}
CODE_BY_REGION = {v: k for k, v in REGION_BY_CODE.items()}

# ---------------------------------------------------------------- 학력 R7000

EDUCATION_BY_CODE = {
    "R7010": "학력무관", "R7020": "중졸이하", "R7030": "고졸",
    "R7040": "대졸(2~3년)", "R7050": "대졸(4년)",
    "R7060": "석사", "R7070": "박사",
}

#: 4년제 재학/졸업자가 지원 가능한 학력 조건.
UNIVERSITY_EDUCATION_CODES = ("R7010", "R7040", "R7050")


def employment_type_of(hire_codes: str | None) -> EmploymentType:
    """`hireTypeLst` 는 쉼표로 여러 개가 올 수 있다.

    인턴이 하나라도 있으면 인턴으로 본다 — 사용자가 찾는 것이 인턴이므로,
    누락(false negative)이 오분류보다 비싸다.
    """
    codes = _split(hire_codes)
    if any(c in INTERN_CODES for c in codes):
        return EmploymentType.INTERN
    for code in codes:
        mapped = EMPLOYMENT_TYPE_BY_CODE.get(code)
        if mapped is not None:
            return mapped
    return EmploymentType.UNKNOWN


def career_level_of(recruit_code: str | None) -> CareerLevel:
    codes = _split(recruit_code)
    levels = {CAREER_LEVEL_BY_CODE.get(c, CareerLevel.UNKNOWN) for c in codes}
    if CareerLevel.BOTH in levels:
        return CareerLevel.BOTH
    if CareerLevel.NEWGRAD in levels and CareerLevel.EXPERIENCED in levels:
        return CareerLevel.BOTH
    if CareerLevel.NEWGRAD in levels:
        return CareerLevel.NEWGRAD
    if CareerLevel.EXPERIENCED in levels:
        return CareerLevel.EXPERIENCED
    return CareerLevel.UNKNOWN


def _split(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]
