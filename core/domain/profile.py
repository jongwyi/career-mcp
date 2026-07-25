"""프로필 도메인. 외부 의존성 없음.

사실(Fact)은 추가만 하고 수정하지 않는다. 수정은 새 Fact를 만들고
기존 Fact 에 superseded_by 를 표시하는 것으로 표현한다.

이유: GPT와 Claude가 같은 프로필을 동시에 쓴다. 덮어쓰기 모델에서는
두 세션이 겹치는 순간 lost update 가 발생하고, 무엇이 사라졌는지조차
알 수 없다. append-only 는 그 상황에서도 이력이 남는다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class FactKind(StrEnum):
    STRENGTH = "strength"
    WEAKNESS = "weakness"
    SKILL = "skill"
    EXPERIENCE = "experience"
    PREFERENCE = "preference"
    GOAL = "goal"


class FactSource(StrEnum):
    """어느 경로로 알게 된 사실인지.

    GPT_IMPORT 는 GPT 대화를 파일로 내보내 흡수한 것이다.
    실시간 연동이 아니라 사용자가 직접 옮기는 단방향 경로다.
    """

    CLAUDE = "claude"
    GPT_IMPORT = "gpt_import"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class Fact:
    kind: FactKind
    content: str
    source: FactSource
    id: int | None = None  # 저장 전에는 None
    evidence: str | None = None  # 주장을 뒷받침하는 구체적 사례
    tags: tuple[str, ...] = ()
    confidence: float = 0.7
    session_ref: str | None = None
    created_at: datetime | None = None
    superseded_by: int | None = None

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("content 는 비어 있을 수 없다")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence 는 0.0~1.0 범위여야 한다: {self.confidence}")

    @property
    def is_active(self) -> bool:
        return self.superseded_by is None

    @property
    def dedupe_hash(self) -> str:
        return fact_hash(self.kind, self.content)


def fact_hash(kind: FactKind, content: str) -> str:
    """중복 임포트 방지용 지문.

    같은 파일을 두 번 넣어도 사실이 두 번 쌓이지 않게 한다.
    활성 Fact 에 대해서만 유일성을 강제한다 — 대체된 Fact 와는 충돌하지 않아야
    같은 내용을 다시 인정하는 경우를 막지 않는다.
    """
    import hashlib
    import re

    normalized = re.sub(r"\s+", " ", content).strip().lower()
    return hashlib.sha256(f"{kind}\x00{normalized}".encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ProfileSnapshot:
    """활성 Fact 를 kind 별로 묶은 읽기 전용 뷰.

    facts 로부터 언제든 재생성 가능한 캐시다. 진실의 원천이 아니다.
    """

    by_kind: Mapping[FactKind, tuple[Fact, ...]]
    fact_count: int
    updated_at: datetime | None = None

    def of(self, kind: FactKind) -> tuple[Fact, ...]:
        return self.by_kind.get(kind, ())

    def is_empty(self) -> bool:
        return self.fact_count == 0


def build_snapshot(
    facts: Iterable[Fact],
    *,
    updated_at: datetime | None = None,
) -> ProfileSnapshot:
    """활성 Fact 만 골라 kind 별로 묶는다. 최신순 정렬."""
    active = [f for f in facts if f.is_active]
    grouped: dict[FactKind, list[Fact]] = {}
    for fact in active:
        grouped.setdefault(fact.kind, []).append(fact)

    ordered = {
        kind: tuple(
            sorted(items, key=lambda f: (f.created_at or datetime.min), reverse=True)
        )
        for kind, items in grouped.items()
    }
    return ProfileSnapshot(
        by_kind=ordered, fact_count=len(active), updated_at=updated_at
    )


def validate_supersede(original: Fact) -> None:
    """대체 가능한 상태인지 확인한다.

    실제 대체(replacement 저장 + superseded_by 연결)는 원자적이어야 하므로
    저장소가 수행한다. 도메인은 규칙만 안다.
    """
    if original.id is None:
        raise ValueError("저장되지 않은 Fact 는 대체할 수 없다")
    if not original.is_active:
        raise ValueError(f"이미 대체된 Fact 다: id={original.id}")


def facts_since(
    facts: Iterable[Fact],
    *,
    since: datetime | None = None,
    source: FactSource | None = None,
) -> tuple[Fact, ...]:
    """profile_diff 용. "GPT에서 뭐가 추가됐나"를 답하는 함수다."""
    result = [
        f
        for f in facts
        if (since is None or (f.created_at is not None and f.created_at > since))
        and (source is None or f.source == source)
    ]
    result.sort(key=lambda f: (f.created_at or datetime.min), reverse=True)
    return tuple(result)
