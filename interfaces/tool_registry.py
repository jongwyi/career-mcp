"""툴 선언의 단일 소스. 전송 계층(stdio / HTTP)과 무관하다.

전송이 지금은 stdio 하나뿐이지만 여기 따로 두는 이유는
docs/REMOTE_GPT_INTEGRATION.md 의 HTTP 경로를 나중에 얹을 때
같은 목록을 그대로 재사용하기 위해서다.

description 작성이 이 파일의 핵심이다.
**모델이 툴을 아예 부르지 않는 것이 이 시스템의 가장 흔한 실패 모드**이므로,
"무엇을 하는가"보다 "언제 불러야 하는가"를 앞세워 쓴다.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from core.application.import_service import ImportService, UnsupportedFormatError
from core.application.profile_service import ProfileService
from core.domain.profile import (
    AttributeKey,
    DiscardReason,
    Fact,
    FactKind,
    FactSource,
)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    handler: Callable[..., Any]


def _fact_out(fact: Fact) -> dict[str, Any]:
    out: dict[str, Any] = {"id": fact.id, "content": fact.content}
    if fact.evidence:
        out["evidence"] = fact.evidence
    if fact.tags:
        out["tags"] = list(fact.tags)
    out["confidence"] = round(fact.confidence, 2)
    out["source"] = str(fact.source)
    return out


def build_profile_tools(
    profile: ProfileService, importer: ImportService
) -> list[ToolSpec]:
    async def profile_read(kinds: list[str] | None = None) -> dict[str, Any]:
        parsed = [FactKind(k) for k in kinds] if kinds else None
        snapshot = await profile.read(kinds=parsed)
        attrs = await profile.attributes()
        missing = attrs.missing_essentials()
        return {
            "fact_count": snapshot.fact_count,
            "attributes": {str(k): v for k, v in attrs.values.items()},
            "missing_attributes": [str(k) for k in missing],
            "missing_note": (
                "지원 자격 판단에 필요한 값이 비어 있다. "
                "대화 중 자연스럽게 물어보고 profile_set 으로 채워라."
                if missing else None
            ),
            "facts": {
                str(kind): [_fact_out(f) for f in facts]
                for kind, facts in snapshot.by_kind.items()
            },
        }

    async def profile_discard(
        fact_ids: list[int], reason: str = "not_mine"
    ) -> dict[str, Any]:
        discarded, errors = [], []
        for fid in fact_ids:
            try:
                fact = await profile.discard(fid, DiscardReason(reason))
                discarded.append({"fact_id": fact.id, "content": fact.content})
            except Exception as exc:
                errors.append(f"{fid}: {exc}")
        return {
            "discarded": discarded,
            "count": len(discarded),
            "errors": errors,
            "reason": reason,
            "note": "삭제하지 않고 비활성화했다. profile_restore 로 되살릴 수 있다",
        }

    async def profile_confirm(fact_ids: list[int]) -> dict[str, Any]:
        n = await profile.verify(fact_ids)
        snapshot = await profile.read()
        remaining = sum(
            1 for facts in snapshot.by_kind.values() for f in facts if not f.is_verified
        )
        return {
            "confirmed": n,
            "unverified_remaining": remaining,
            "note": "확인된 사실은 자소서 근거로 안심하고 인용할 수 있다",
        }

    async def profile_evidence(fact_ids: list[int]) -> dict[str, Any]:
        snapshot = await profile.read()
        wanted = set(fact_ids)
        out = []
        for facts in snapshot.by_kind.values():
            for f in facts:
                if f.id in wanted:
                    out.append(
                        {
                            "fact_id": f.id,
                            "kind": str(f.kind),
                            "content": f.content,
                            "evidence": f.evidence,
                            "verified": f.is_verified,
                        }
                    )
        return {"count": len(out), "facts": out}

    async def profile_restore(fact_id: int) -> dict[str, Any]:
        fact = await profile.restore(fact_id)
        return {"restored_fact_id": fact.id, "content": fact.content}

    async def profile_set(key: str, value: str) -> dict[str, Any]:
        attr = AttributeKey(key)
        await profile.set_attribute(attr, value)
        attrs = await profile.attributes()
        return {
            "key": str(attr),
            "value": value,
            "missing_attributes": [str(k) for k in attrs.missing_essentials()],
        }

    async def profile_append(
        kind: str,
        content: str,
        evidence: str | None = None,
        tags: list[str] | None = None,
        confidence: float = 0.7,
    ) -> dict[str, Any]:
        result = await profile.append(
            FactKind(kind),
            content,
            evidence=evidence,
            tags=tuple(tags or ()),
            confidence=confidence,
        )
        return {
            "created": result.created,
            "fact": _fact_out(result.fact),
            "note": None if result.created else "이미 같은 내용이 기록되어 있어 추가하지 않았다",
        }

    async def profile_revise(
        fact_id: int,
        new_content: str,
        evidence: str | None = None,
        confidence: float | None = None,
    ) -> dict[str, Any]:
        saved = await profile.revise(
            fact_id, new_content, evidence=evidence, confidence=confidence
        )
        return {
            "superseded_fact_id": fact_id,
            "new_fact": _fact_out(saved),
            "note": "기존 사실은 삭제되지 않고 이력으로 남았다",
        }

    async def profile_diff(
        since: str | None = None, source: str | None = None
    ) -> dict[str, Any]:
        since_dt = datetime.fromisoformat(since) if since else None
        src = FactSource(source) if source else None
        facts = await profile.diff(since=since_dt, source=src)
        return {
            "count": len(facts),
            "facts": [
                {**_fact_out(f), "kind": str(f.kind),
                 "created_at": f.created_at.isoformat() if f.created_at else None}
                for f in facts
            ],
        }

    async def profile_import(file_path: str) -> dict[str, Any]:
        import json

        path = Path(file_path).expanduser()
        if not path.is_file():
            return {"error": f"파일을 찾을 수 없다: {path}"}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return {"error": f"JSON 파싱 실패: {exc}"}

        try:
            report = await importer.import_payload(payload)
        except UnsupportedFormatError as exc:
            return {"error": str(exc)}

        return {
            "added": len(report.added),
            "added_by_kind": report.added_by_kind,
            "duplicates": report.duplicates,
            "errors": list(report.errors),
            "facts": [{**_fact_out(f), "kind": str(f.kind)} for f in report.added],
        }

    return [
        ToolSpec(
            "profile_read",
            "사용자의 축적된 프로필(강점·약점·역량·경험·선호·목표)을 읽는다. "
            "**대화를 시작할 때 반드시 한 번 호출한다.** "
            "또 사용자가 자기 자신에 대해 이야기하거나, 진로·지원·자소서 관련 조언을 "
            "요청하거나, 채용 공고와의 적합성을 물을 때 먼저 호출한다. "
            "프로필을 모르는 상태로 조언하면 일반론밖에 나오지 않는다. "
            "kinds 로 특정 종류만 좁힐 수 있다(strength, weakness, skill, experience, preference, goal).",
            profile_read,
        ),
        ToolSpec(
            "profile_append",
            "사용자에 대한 새로 알게 된 사실을 프로필에 기록한다. "
            "대화 중 사용자가 자신의 경험·역량·강점·약점·선호·목표를 드러냈고 "
            "그것이 아직 프로필에 없을 때 호출한다. "
            "**호출 전에 사용자에게 무엇을 기록할지 알리고, 호출 후 결과를 요약해 보여준다.** "
            "조용히 기록하면 사용자가 자기 프로필을 신뢰할 수 없게 된다. "
            "content 는 한 문장으로 된 하나의 사실이어야 한다 — 여러 개를 묶지 말고 나눠서 여러 번 호출한다. "
            "evidence 에는 그렇게 판단한 구체적 근거를 넣는다. 근거 없는 강점은 "
            "매칭 점수는 올리지만 지원서에는 쓸 수 없다. "
            "같은 내용이 이미 있으면 중복으로 판정되어 추가되지 않는다(created=false).",
            profile_append,
        ),
        ToolSpec(
            "profile_revise",
            "기존 프로필 사실을 새 내용으로 대체한다. "
            "사용자의 상황이 바뀌었거나, 기록된 내용이 부정확하다고 사용자가 알려줄 때 호출한다. "
            "기존 사실은 삭제되지 않고 이력으로 남으므로 변화 추적이 가능하다. "
            "fact_id 는 profile_read 나 profile_diff 로 먼저 확인한다. "
            "내용이 실제로 바뀌지 않으면 거부된다.",
            profile_revise,
        ),
        ToolSpec(
            "profile_diff",
            "최근에 추가된 프로필 사실만 조회한다. "
            "**세션을 시작할 때 profile_read 와 함께 호출해 '그동안 무엇이 늘었는지'를 사용자에게 알린다.** "
            "특히 source='gpt_import' 로 호출하면 사용자가 ChatGPT 대화에서 옮겨온 내용만 볼 수 있다. "
            "since 는 ISO8601 형식(예: '2026-07-01T00:00:00+09:00'), "
            "source 는 claude / gpt_import / manual 중 하나다.",
            profile_diff,
        ),
        ToolSpec(
            "profile_discard",
            "프로필의 특정 사실을 비활성화한다. **삭제가 아니라 보류다.** "
            "사용자가 '그건 내 정보 아니야', '그건 사실과 달라', "
            "'그건 빼줘' 라고 할 때 호출한다. "
            "임포트한 파일에 다른 사람의 정보가 섞여 있을 수 있으므로 "
            "임포트 직후 결과를 보여주고 아닌 것이 있는지 물어보는 것이 좋다. "
            "reason: not_mine(다른 사람 정보) / incorrect(사실과 다름) / "
            "outdated(더는 해당 없음) / other. "
            "내용이 바뀐 것뿐이라면 discard 가 아니라 profile_revise 를 쓴다. "
            "여러 건을 한 번에 넘길 수 있다: fact_ids=[38, 45, 52]",
            profile_discard,
        ),
        ToolSpec(
            "profile_confirm",
            "사실이 정확하다고 사용자가 확인했음을 표시한다. "
            "**임포트된 사실에는 과장이 섞인다** — GPT 가 대화를 요약하면서 "
            "'기획을 논의했다'를 '기획에 참여했다'로 적는 식이다. "
            "사용자가 '맞아', '그건 정확해' 라고 확인해 줄 때 호출한다. "
            "확인되지 않은 사실은 매칭에서 unverified 로 표시되어 "
            "자소서 근거로 확정적으로 쓰이지 않는다. "
            "여러 건을 한 번에: fact_ids=[38, 45, 52]",
            profile_confirm,
        ),
        ToolSpec(
            "profile_evidence",
            "특정 사실들의 **구체적 근거(evidence)** 를 가져온다. "
            "jobs_match 응답에는 근거가 빠져 있다 — 매번 전부 보내면 낭비이기 때문이다. "
            "**지원서에 쓸 재료를 만들거나 자소서 문장을 쓸 때 호출한다.** "
            "매칭에서 인용한 fact_id 들을 넘기면 된다.",
            profile_evidence,
        ),
        ToolSpec(
            "profile_restore",
            "보류했던 사실을 되살린다. 사용자가 '아까 뺀 거 다시 넣어줘' 라고 할 때 호출한다.",
            profile_restore,
        ),
        ToolSpec(
            "profile_set",
            "지원 자격 판단에 쓰이는 핵심 값을 설정한다. "
            "**공고 대부분이 연령(만 15~34세)·학력·재학 여부·어학을 조건으로 걸기 때문에 "
            "이 값들이 없으면 지원 가능 여부 자체를 판단할 수 없다.** "
            "profile_read 의 missing_attributes 에 항목이 있으면 "
            "대화 중 자연스럽게 물어보고 채워라. "
            "key: birth_year / school / major / double_major / enrollment_status "
            "(재학·휴학·졸업·졸업예정) / expected_graduation / languages "
            "(예: 'TOEIC 850, OPIc IH') / certifications / military_status / "
            "location_preference",
            profile_set,
        ),
        ToolSpec(
            "profile_import",
            "ChatGPT 대화에서 내보낸 프로필 JSON 파일을 읽어 프로필에 흡수한다. "
            "사용자가 '임포트해줘', '이 파일 넣어줘' 라고 하거나 "
            "profile-import-*.json 같은 파일을 언급할 때 호출한다. "
            "형식 명세는 docs/PROFILE_IMPORT_FORMAT.md 에 있다. "
            "이미 있는 사실은 자동으로 걸러지므로 같은 파일을 여러 번 넣어도 안전하다. "
            "**결과(신규/중복/오류 건수)를 반드시 사용자에게 요약해 보여준다.**",
            profile_import,
        ),
    ]


def register(mcp: Any, specs: Sequence[ToolSpec]) -> None:
    """FastMCP 인스턴스에 툴을 등록한다. 전송 계층이 늘어나도 이 함수만 늘어난다."""
    for spec in specs:
        mcp.tool(name=spec.name, description=spec.description)(spec.handler)
