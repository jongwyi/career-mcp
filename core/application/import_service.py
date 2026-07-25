"""GPT 대화 내보내기 파일 → 프로필 Fact.

형식 명세: docs/PROFILE_IMPORT_FORMAT.md

원칙 두 가지.
1. 임포트는 **추가 전용**이다. 기존 사실을 수정하지 않는다 (그건 revise 의 일).
2. 한 항목이 잘못돼도 나머지는 넣는다. 대신 무엇이 왜 빠졌는지 전부 보고한다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from core.domain.profile import Fact, FactKind, FactSource
from core.ports.store import ProfileStore

SUPPORTED_FORMAT = "career-profile-import/v1"


@dataclass(frozen=True, slots=True)
class ImportReport:
    added: tuple[Fact, ...] = ()
    duplicates: int = 0
    errors: tuple[str, ...] = ()

    @property
    def added_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for fact in self.added:
            counts[fact.kind] = counts.get(fact.kind, 0) + 1
        return counts


class UnsupportedFormatError(ValueError):
    pass


class ImportService:
    def __init__(self, store: ProfileStore) -> None:
        self._store = store

    async def import_payload(self, payload: Mapping[str, Any]) -> ImportReport:
        fmt = payload.get("format")
        if fmt != SUPPORTED_FORMAT:
            # 추측해서 읽지 않는다. 잘못 해석된 프로필은 조용히 매칭 품질을 떨어뜨리고
            # 원인 추적이 어렵다.
            raise UnsupportedFormatError(
                f"지원하지 않는 형식이다: {fmt!r} (기대: {SUPPORTED_FORMAT!r})"
            )

        raw_facts = payload.get("facts")
        if not isinstance(raw_facts, Sequence) or isinstance(raw_facts, (str, bytes)):
            raise UnsupportedFormatError("facts 는 배열이어야 한다")

        existing = {f.dedupe_hash for f in await self._store.list_facts(active_only=True)}
        seen_in_file: set[str] = set()

        added: list[Fact] = []
        errors: list[str] = []
        duplicates = 0

        for index, item in enumerate(raw_facts):
            try:
                candidate = self._to_fact(item)
            except ValueError as exc:
                errors.append(f"facts[{index}] — {exc}")
                continue

            digest = candidate.dedupe_hash
            if digest in existing or digest in seen_in_file:
                duplicates += 1
                continue

            seen_in_file.add(digest)
            added.append(await self._store.add_fact(candidate))

        return ImportReport(
            added=tuple(added), duplicates=duplicates, errors=tuple(errors)
        )

    # ---------------------------------------------------------------- 내부

    @staticmethod
    def _to_fact(item: Any) -> Fact:
        if not isinstance(item, Mapping):
            raise ValueError("항목이 객체가 아니다")

        raw_kind = item.get("kind")
        try:
            kind = FactKind(raw_kind)
        except ValueError:
            allowed = ", ".join(k.value for k in FactKind)
            raise ValueError(f"kind {raw_kind!r} 은 허용되지 않는다 (허용: {allowed})") from None

        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content 가 비어 있거나 문자열이 아니다")

        evidence = item.get("evidence")
        if evidence is not None and not isinstance(evidence, str):
            raise ValueError("evidence 는 문자열이어야 한다")

        raw_tags = item.get("tags", [])
        if not isinstance(raw_tags, Sequence) or isinstance(raw_tags, (str, bytes)):
            raise ValueError("tags 는 배열이어야 한다")
        tags = tuple(str(t) for t in raw_tags)

        confidence = item.get("confidence", 0.7)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            raise ValueError(f"confidence 가 숫자가 아니다: {confidence!r}") from None

        # Fact.__post_init__ 이 범위·공백을 한 번 더 검증한다.
        return Fact(
            kind=kind,
            content=content,
            source=FactSource.GPT_IMPORT,
            evidence=evidence,
            tags=tags,
            confidence=confidence,
        )
