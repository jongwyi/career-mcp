"""프로필 유스케이스. ports 인터페이스에만 의존한다 — Supabase 를 모른다."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from core.application.snapshot import refresh_snapshot
from core.domain.profile import (
    AttributeKey,
    DiscardReason,
    Fact,
    FactKind,
    FactSource,
    ProfileAttributes,
    ProfileSnapshot,
    build_snapshot,
    facts_since,
    validate_supersede,
)
from core.ports.store import ProfileStore


@dataclass(frozen=True, slots=True)
class AppendResult:
    """중복이면 fact 는 기존 것이고 created 가 False 다."""

    fact: Fact
    created: bool


class ProfileService:
    def __init__(self, store: ProfileStore) -> None:
        self._store = store

    # ---------------------------------------------------------------- 읽기

    async def read(self, *, kinds: Sequence[FactKind] | None = None) -> ProfileSnapshot:
        """항상 facts 에서 다시 만든다.

        캐시된 스냅샷을 읽지 않는 것은 의도적이다. 수백 건 규모에서 재생성은 싸고,
        캐시를 신뢰하면 갱신 누락이 조용한 오답으로 이어진다.
        저장된 스냅샷은 점검용이지 정답의 근거가 아니다.
        """
        facts = await self._store.list_facts(kinds=kinds, active_only=True)
        return build_snapshot(facts)

    async def diff(
        self,
        *,
        since: datetime | None = None,
        source: FactSource | None = None,
    ) -> tuple[Fact, ...]:
        """세션 시작 시 "그동안 뭐가 늘었나"를 답한다."""
        facts = await self._store.list_facts(active_only=True, since=since, source=source)
        return facts_since(facts, since=since, source=source)

    # ---------------------------------------------------------------- 쓰기

    async def append(
        self,
        kind: FactKind,
        content: str,
        *,
        evidence: str | None = None,
        tags: Sequence[str] = (),
        confidence: float = 0.7,
        source: FactSource = FactSource.CLAUDE,
        session_ref: str | None = None,
    ) -> AppendResult:
        candidate = Fact(
            kind=kind,
            content=content,
            source=source,
            evidence=evidence,
            tags=tuple(tags),
            confidence=confidence,
            session_ref=session_ref,
        )

        # DB 에도 부분 유니크 인덱스가 있지만, 여기서 먼저 걸러야
        # 예외가 아니라 "이미 있음"이라는 결과로 돌려줄 수 있다.
        existing = await self._find_active_by_hash(candidate.dedupe_hash)
        if existing is not None:
            return AppendResult(fact=existing, created=False)

        saved = await self._store.add_fact(candidate)
        await self._refresh_snapshot()
        return AppendResult(fact=saved, created=True)

    async def revise(
        self,
        fact_id: int,
        new_content: str,
        *,
        evidence: str | None = None,
        confidence: float | None = None,
    ) -> Fact:
        """기존 사실을 대체한다. 덮어쓰지 않고 이력을 남긴다."""
        original = await self._store.get_fact(fact_id)
        if original is None:
            raise LookupError(f"Fact 를 찾을 수 없다: id={fact_id}")
        validate_supersede(original)

        replacement = replace(
            original,
            id=None,
            content=new_content,
            evidence=evidence if evidence is not None else original.evidence,
            confidence=confidence if confidence is not None else original.confidence,
            created_at=None,
            superseded_by=None,
        )
        saved = await self._store.supersede_fact(fact_id, replacement)
        await self._refresh_snapshot()
        return saved

    async def discard(
        self, fact_id: int, reason: DiscardReason = DiscardReason.NOT_MINE
    ) -> Fact:
        """내 것이 아니거나 틀린 사실을 비활성화한다. 지우지 않는다."""
        fact = await self._store.discard_fact(fact_id, reason=reason)
        await self._refresh_snapshot()
        return fact

    async def restore(self, fact_id: int) -> Fact:
        fact = await self._store.restore_fact(fact_id)
        await self._refresh_snapshot()
        return fact

    async def discarded(self) -> Sequence[Fact]:
        return await self._store.list_discarded()

    async def stamp(self) -> datetime | None:
        """프로필이 마지막으로 바뀐 시각. 평가 캐시의 무효화 기준 중 하나다."""
        snapshot = await self._store.load_snapshot()
        return snapshot.updated_at if snapshot else None

    async def verify(self, fact_ids: Sequence[int]) -> int:
        return await self._store.verify_facts(fact_ids)

    async def attributes(self) -> ProfileAttributes:
        return await self._store.get_attributes()

    async def set_attribute(self, key: AttributeKey, value: str) -> None:
        if not value.strip():
            raise ValueError("값이 비어 있다")
        await self._store.set_attribute(key, value.strip())

    # ---------------------------------------------------------------- 내부

    async def _find_active_by_hash(self, dedupe_hash: str) -> Fact | None:
        for fact in await self._store.list_facts(active_only=True):
            if fact.dedupe_hash == dedupe_hash:
                return fact
        return None

    async def _refresh_snapshot(self) -> None:
        await refresh_snapshot(self._store)
