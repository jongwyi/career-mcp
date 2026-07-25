"""지원 자격 제한 감지. 순수 함수, 외부 의존성 없음.

공공기관 채용에는 장애인 전형·보훈 제한경쟁·사회형평 채용처럼
특정 자격을 갖춘 사람만 지원할 수 있는 공고가 많다. 실측으로 진행 중
공고의 절반 가까이가 여기 해당했다. 걸러내지 않으면 추천 슬롯의 절반이
지원할 수 없는 공고로 채워진다.

두 가지 원칙으로 설계했다.

1. **버리지 않고 표시한다.** 사용자가 실제로 해당될 수 있다.
   기본 조회에서 빼되, 몇 건을 뺐는지는 항상 보고한다.
2. **제목을 우선 본다.** 단, 기관명을 먼저 제거한다 —
   '한국장애인고용공단'의 '장애'는 제한이 아니라 발신자 이름이다.
   우대사항(preferred)은 보지 않는다 — '장애인 우대'는 제한이 아니다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

#: 제목에 나오면 사실상 확정인 신호. 기관명 제거 후 검사한다.
_TITLE_PATTERNS: dict[str, str] = {
    "장애": r"장애",
    "보훈": r"보훈|국가유공",
    "제한경쟁": r"제한\s*경쟁",
    "사회형평": r"사회\s*형평",
    "지역인재": r"지역\s*인재|지역\s*제한",
    "북한이탈": r"북한이탈|새터민",
    "경력단절": r"경력\s*단절",
}

#: 지원자격 본문에서만 인정하는 강한 신호. 약한 표현은 오탐이 많아 뺐다.
_REQUIREMENT_PATTERNS: dict[str, str] = {
    "장애": r"장애인\s*(전형|제한|만\s*지원|에\s*한함|에\s*한하여)|중증\s*장애",
    "보훈": r"보훈\s*(대상자\s*)?(전형|제한)|국가유공자\s*(전형|제한)",
    "제한경쟁": r"제한\s*경쟁",
    "사회형평": r"사회\s*형평",
    "지역인재": r"지역\s*인재\s*(전형|제한)|거주자?\s*에\s*한",
    "북한이탈": r"북한이탈주민\s*(전형|제한)",
}


#: 기관·시설 이름에 들어가는 단어들. 제한 신호가 아니다.
#: '[전주보훈요양원] 청년인턴' 의 '보훈'은 발신자이지 자격 조건이 아니다.
_INSTITUTION_NOISE = re.compile(
    r"보훈(요양원|병원|원|공단|복지|의료)|장애인(고용공단|개발원|공단|복지|체육)"
)


def detect_restrictions(
    title: str,
    *,
    company: str | None = None,
    requirements: Sequence[str] = (),
) -> tuple[str, ...]:
    """지원 자격 제한 태그를 돌려준다. 없으면 빈 튜플."""
    headline = title or ""
    if company:
        # 기관명이 제목에 그대로 박혀 있는 경우가 많다. 먼저 지운다.
        headline = headline.replace(company, " ")
        # '한국장애인고용공단 서울지역본부'처럼 변형된 형태도 흔하다.
        for token in re.split(r"[\s()\[\]]+", company):
            if len(token) >= 4:
                headline = headline.replace(token, " ")
    headline = _INSTITUTION_NOISE.sub(" ", headline)

    found = {tag for tag, pat in _TITLE_PATTERNS.items() if re.search(pat, headline)}

    body = " ".join(requirements)
    found |= {tag for tag, pat in _REQUIREMENT_PATTERNS.items() if re.search(pat, body)}

    return tuple(sorted(found))
