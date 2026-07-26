"""ProfileStore 의 Supabase(PostgREST) 구현.

직접 Postgres 접속 대신 PostgREST(HTTPS)를 쓴다.
Supabase 신규 프로젝트의 직접 접속 호스트는 IPv6 전용이라 환경에 따라 막히지만,
`https://<ref>.supabase.co/rest/v1` 은 어디서나 열린다.

이 파일은 core 를 import 하지만 core 는 이 파일을 모른다. 의존성 방향은 항상 안쪽이다.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import httpx

from core.domain.profile import (
    AttributeKey,
    DiscardReason,
    Fact,
    FactKind,
    FactSource,
    ProfileAttributes,
    ProfileSnapshot,
    build_snapshot,
)


class SupabaseError(RuntimeError):
    pass


class SupabaseClientMixin:
    """PostgREST 접속 공통부. 저장소 구현들이 공유한다."""

    def __init__(
        self,
        url: str,
        service_key: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not url or not service_key:
            raise ValueError("SUPABASE_URL 과 SUPABASE_SERVICE_KEY 가 필요하다")
        if service_key.startswith("sb_publishable_"):
            # 조용히 실패하면 원인 추적에 시간이 걸린다. 여기서 바로 잡는다.
            raise ValueError(
                "퍼블리셔블 키가 들어왔다. RLS 때문에 프로필을 읽을 수 없다. "
                "Project Settings > API Keys 의 secret 키(sb_secret_...)를 쓸 것"
            )
        self._base = f"{url.rstrip('/')}/rest/v1"
        self._headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }
        self._client = client or httpx.AsyncClient(timeout=30)

    @classmethod
    def from_env(cls, *, client: httpx.AsyncClient | None = None) -> Any:
        return cls(
            os.environ.get("SUPABASE_URL", ""),
            os.environ.get("SUPABASE_SERVICE_KEY", ""),
            client=client,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json: Any = None,
        prefer: str | None = None,
    ) -> Any:
        headers = dict(self._headers)
        if prefer:
            headers["Prefer"] = prefer
        response = await self._client.request(
            method, f"{self._base}{path}", params=params, json=json, headers=headers
        )
        if response.status_code >= 400:
            raise SupabaseError(
                f"{method} {path} -> {response.status_code}: {response.text[:300]}"
            )
        if not response.content:
            return None
        return response.json()

    async def _count(self, path: str, params: Mapping[str, str]) -> int:
        """Content-Range 헤더로 건수만 받는다. 행을 끌어오지 않는다."""
        headers = {**self._headers, "Prefer": "count=exact", "Range": "0-0"}
        response = await self._client.get(
            f"{self._base}{path}", params={**params, "select": "id"}, headers=headers
        )
        if response.status_code >= 400:
            raise SupabaseError(f"count {path} -> {response.status_code}")
        total = response.headers.get("content-range", "*/0").split("/")[-1]
        return int(total) if total.isdigit() else 0


class SupabaseProfileStore(SupabaseClientMixin):
    """core.ports.store.ProfileStore 를 구현한다."""

    # ---------------------------------------------------------------- 매핑

    @staticmethod
    def _to_fact(row: Mapping[str, Any]) -> Fact:
        created = row.get("created_at")
        return Fact(
            id=row["id"],
            kind=FactKind(row["kind"]),
            content=row["content"],
            source=FactSource(row["source"]),
            evidence=row.get("evidence"),
            tags=tuple(row.get("tags") or ()),
            confidence=row.get("confidence", 0.7),
            session_ref=row.get("session_ref"),
            created_at=datetime.fromisoformat(created) if created else None,
            superseded_by=row.get("superseded_by"),
            discarded_at=(
                datetime.fromisoformat(row["discarded_at"])
                if row.get("discarded_at")
                else None
            ),
            discard_reason=(
                DiscardReason(row["discard_reason"])
                if row.get("discard_reason")
                else None
            ),
            verified_at=(
                datetime.fromisoformat(row["verified_at"])
                if row.get("verified_at")
                else None
            ),
        )

    @staticmethod
    def _to_row(fact: Fact) -> dict[str, Any]:
        """dedupe_hash 는 도메인이 계산한다. DB 가 다시 계산하지 않는다 —
        정규화 규칙이 두 곳에 생기면 반드시 어긋난다."""
        return {
            "kind": str(fact.kind),
            "content": fact.content,
            "evidence": fact.evidence,
            "tags": list(fact.tags),
            "confidence": fact.confidence,
            "source": str(fact.source),
            "session_ref": fact.session_ref,
            "dedupe_hash": fact.dedupe_hash,
        }

    # ---------------------------------------------------------------- 포트 구현

    async def add_fact(self, fact: Fact) -> Fact:
        rows = await self._request(
            "POST",
            "/profile_facts",
            json=self._to_row(fact),
            prefer="return=representation",
        )
        return self._to_fact(rows[0])

    async def get_fact(self, fact_id: int) -> Fact | None:
        rows = await self._request(
            "GET", "/profile_facts", params={"id": f"eq.{fact_id}", "select": "*"}
        )
        return self._to_fact(rows[0]) if rows else None

    async def list_facts(
        self,
        *,
        kinds: Sequence[FactKind] | None = None,
        active_only: bool = True,
        since: datetime | None = None,
        source: FactSource | None = None,
    ) -> Sequence[Fact]:
        params: dict[str, str] = {"select": "*", "order": "created_at.desc"}
        if active_only:
            params["superseded_by"] = "is.null"
            params["discarded_at"] = "is.null"
        if kinds:
            params["kind"] = f"in.({','.join(str(k) for k in kinds)})"
        if source:
            params["source"] = f"eq.{source}"
        if since:
            params["created_at"] = f"gt.{since.isoformat()}"
        rows = await self._request("GET", "/profile_facts", params=params)
        return [self._to_fact(r) for r in rows]

    async def supersede_fact(self, fact_id: int, replacement: Fact) -> Fact:
        """RPC 로 처리한다. PostgREST 호출 두 번은 원자적이지 않다."""
        result = await self._request(
            "POST",
            "/rpc/supersede_fact",
            json={"p_fact_id": fact_id, "p_new": self._to_row(replacement)},
        )
        row = result[0] if isinstance(result, list) else result
        return self._to_fact(row)

    async def discard_fact(self, fact_id: int, *, reason: DiscardReason) -> Fact:
        rows = await self._request(
            "PATCH",
            "/profile_facts",
            params={"id": f"eq.{fact_id}", "discarded_at": "is.null"},
            json={
                "discarded_at": datetime.now().astimezone().isoformat(),
                "discard_reason": str(reason),
            },
            prefer="return=representation",
        )
        if not rows:
            raise LookupError(f"보류할 수 없다 (없거나 이미 보류됨): id={fact_id}")
        return self._to_fact(rows[0])

    async def restore_fact(self, fact_id: int) -> Fact:
        rows = await self._request(
            "PATCH",
            "/profile_facts",
            params={"id": f"eq.{fact_id}"},
            json={"discarded_at": None, "discard_reason": None},
            prefer="return=representation",
        )
        if not rows:
            raise LookupError(f"되살릴 수 없다: id={fact_id}")
        return self._to_fact(rows[0])

    async def list_discarded(self) -> Sequence[Fact]:
        rows = await self._request(
            "GET",
            "/profile_facts",
            params={
                "select": "*",
                "discarded_at": "not.is.null",
                "order": "discarded_at.desc",
            },
        )
        return [self._to_fact(r) for r in rows]

    async def verify_facts(self, fact_ids: Sequence[int]) -> int:
        if not fact_ids:
            return 0
        rows = await self._request(
            "PATCH",
            "/profile_facts",
            params={"id": f"in.({','.join(str(i) for i in fact_ids)})"},
            json={"verified_at": datetime.now().astimezone().isoformat()},
            prefer="return=representation",
        )
        return len(rows or [])

    async def get_attributes(self) -> ProfileAttributes:
        rows = await self._request(
            "GET", "/profile_attributes", params={"select": "key,value"}
        )
        values: dict[AttributeKey, str] = {}
        for row in rows or []:
            try:
                values[AttributeKey(row["key"])] = row["value"]
            except ValueError:
                continue  # 알 수 없는 키는 무시한다 (스키마가 앞서갈 수 있다)
        return ProfileAttributes(values=values)

    async def set_attribute(self, key: AttributeKey, value: str) -> None:
        await self._request(
            "POST",
            "/profile_attributes",
            params={"on_conflict": "key"},
            json={
                "key": str(key),
                "value": value,
                "updated_at": datetime.now().astimezone().isoformat(),
            },
            prefer="resolution=merge-duplicates,return=minimal",
        )

    async def load_snapshot(self) -> ProfileSnapshot | None:
        rows = await self._request(
            "GET", "/profile_snapshot", params={"id": "eq.1", "select": "*"}
        )
        if not rows:
            return None
        row = rows[0]
        facts = [self._to_fact(f) for f in row["payload"].get("facts", [])]
        return build_snapshot(
            facts, updated_at=datetime.fromisoformat(row["updated_at"])
        )

    async def save_snapshot(self, snapshot: ProfileSnapshot) -> None:
        payload = {
            "facts": [
                {
                    "id": f.id,
                    "kind": str(f.kind),
                    "content": f.content,
                    "evidence": f.evidence,
                    "tags": list(f.tags),
                    "confidence": f.confidence,
                    "source": str(f.source),
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                }
                for facts in snapshot.by_kind.values()
                for f in facts
            ]
        }
        await self._request(
            "POST",
            "/profile_snapshot",
            json={
                "id": 1,
                "payload": payload,
                "fact_count": snapshot.fact_count,
                "updated_at": datetime.now().astimezone().isoformat(),
            },
            prefer="resolution=merge-duplicates,return=minimal",
        )
