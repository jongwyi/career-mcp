"""스냅샷 갱신. Fact 를 추가하는 모든 유스케이스가 공유한다.

스냅샷은 facts 에서 언제든 재생성 가능한 캐시이고 정답의 근거가 아니다.
그래도 갱신을 빠뜨리면 점검용이라는 용도조차 못 하므로, 쓰기 경로마다
같은 함수를 부르도록 한 곳에 모아둔다.
"""

from __future__ import annotations

from core.domain.profile import build_snapshot
from core.ports.store import ProfileStore


async def refresh_snapshot(store: ProfileStore) -> None:
    facts = await store.list_facts(active_only=True)
    await store.save_snapshot(build_snapshot(facts))
