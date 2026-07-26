"""공고 조회·매칭 툴.

출력 크기 설계가 핵심이다. 후보 목록에는 jd_text 를 넣지 않는다 —
40건 × 2,000자면 컨텍스트가 순위 매기기 전에 소진된다.
목록은 '순위를 매기기에 충분한 만큼', 상세는 '깊게 분석할 만큼'을 준다.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

from core.application.job_query_service import JobQueryService
from core.application.match_service import MatchService, attributions_for
from core.domain.job import CareerLevel, EmploymentType, InterestStatus, JobPosting
from core.domain.match import Evidence, Gap, MatchFilter, ScoredJob, Severity
from interfaces.tool_registry import ToolSpec

#: 후보 1건당 요건을 몇 개까지 보여줄지. 순위 매기기에는 이 정도면 충분하다.
BRIEF_REQUIREMENTS = 6


def _days_left(deadline: date | None) -> int | None:
    return (deadline - date.today()).days if deadline else None


def _brief(job: JobPosting) -> dict[str, Any]:
    out: dict[str, Any] = {
        "job_id": job.id,
        "title": job.title,
        "company": job.company,
        "deadline": job.deadline.isoformat() if job.deadline else None,
        "days_left": _days_left(job.deadline),
        "location": job.location,
        "employment_type": str(job.employment_type),
        "career_level": str(job.career_level),
    }
    if job.education:
        out["education"] = job.education
    if job.job_field:
        out["job_field"] = job.job_field
    if job.headcount:
        out["headcount"] = job.headcount
    if job.requirements:
        # 요건 전문은 job_requirements 로 따로 가져간다.
        # 측정 결과 요건이 응답의 절반 가까이를 차지했는데,
        # 깊게 보는 건 상위 몇 건뿐이라 나머지는 읽히지 않고 버려졌다.
        out["requirement_count"] = len(job.requirements)
    if job.restrictions:
        out["restrictions"] = list(job.restrictions)
    return out


def _full(job: JobPosting) -> dict[str, Any]:
    return {
        **_brief(job),
        "url": job.url,
        "source": job.key.source_id,
        "status": str(job.status),
        "requirements": list(job.requirements),
        "preferred": list(job.preferred),
        "jd_text": job.jd_text,
    }


def _parse_filter(
    keyword: str | None,
    employment_type: str | None,
    career_level: str | None,
    location: str | None,
    limit: int,
    include_closed: bool,
) -> MatchFilter:
    if employment_type or career_level:
        return MatchFilter(
            keyword=keyword,
            employment_types=(EmploymentType(employment_type),) if employment_type else (),
            career_levels=(CareerLevel(career_level),) if career_level else (),
            location=location,
            limit=limit,
            include_closed=include_closed,
            deadline_after=None if include_closed else date.today(),
        )
    return MatchFilter.for_newgrad_intern(
        keyword=keyword,
        location=location,
        limit=limit,
        include_closed=include_closed,
        deadline_after=None if include_closed else date.today(),
    )


def build_job_tools(queries: JobQueryService, matcher: MatchService) -> list[ToolSpec]:
    async def jobs_search(
        keyword: str | None = None,
        employment_type: str | None = None,
        career_level: str | None = None,
        location: str | None = None,
        limit: int = 20,
        include_closed: bool = False,
        include_restricted: bool = False,
    ) -> dict[str, Any]:
        flt = _parse_filter(
            keyword, employment_type, career_level, location, limit, include_closed
        )
        flt = replace(flt, include_restricted=include_restricted)
        found = tuple(await queries.search(flt))
        return {
            "count": len(found),
            "jobs": [_brief(j) for j in found],
            "attribution": list(attributions_for(found)),
        }

    async def jobs_match(
        limit: int = 8,
        keyword: str | None = None,
        location: str | None = None,
        include_restricted: bool = False,
    ) -> dict[str, Any]:
        base = MatchFilter.for_newgrad_intern(
            keyword=keyword,
            location=location,
            limit=limit,
            include_restricted=include_restricted,
        )
        context = await matcher.candidates(base)
        excluded = await matcher.restricted_count(base) if not include_restricted else 0
        snapshot = context.candidates.profile
        prev = context.previous_scores

        # 프로필 계층화 — 요건 대조의 근거가 되는 kind 만 개별로 싣는다.
        # goal/preference 는 방향이지 근거가 아니라 한 줄로 압축한다.
        # evidence 는 지원서 재료를 쓸 때만 필요하므로 profile_evidence 로 뺐다.
        evidence_kinds = ("skill", "experience", "strength")
        evidence_facts: dict[str, list[dict[str, Any]]] = {}
        direction: dict[str, list[str]] = {}
        unverified = 0
        for kind, facts in snapshot.by_kind.items():
            if str(kind) in evidence_kinds:
                items = []
                for f in facts:
                    items.append(
                        {"fact_id": f.id, "content": f.content}
                        if f.is_verified
                        else {"fact_id": f.id, "content": f.content, "unverified": True}
                    )
                    unverified += 0 if f.is_verified else 1
                evidence_facts[str(kind)] = items
            else:
                direction[str(kind)] = [f.content for f in facts]

        return {
            "profile": {
                "fact_count": snapshot.fact_count,
                "evidence_facts": evidence_facts,
                "direction": direction,
                "unverified_count": unverified,
                "unverified_note": (
                    f"근거 사실 중 {unverified}건이 아직 사용자 확인을 거치지 않았다. "
                    "임포트된 사실에는 과장이 섞일 수 있으므로("
                    "'논의했다'가 '참여했다'로 기록되는 등) "
                    "자소서 근거로 인용하기 전에 사용자에게 확인하고 "
                    "profile_confirm 으로 표시하라."
                    if unverified else None
                ),
                "evidence_note": (
                    "구체적 근거(evidence)는 여기 없다. "
                    "지원서 재료를 쓸 때 profile_evidence(fact_ids) 로 가져가라."
                ),
            },
            "fresh": [
                {**_brief(j), **({"previous_score": prev[j.id].score} if j.id in prev else {})}
                for j in context.fresh
            ],
            "cached": [
                {
                    "job_id": j.id,
                    "title": j.title,
                    "company": j.company,
                    "deadline": j.deadline.isoformat() if j.deadline else None,
                    "days_left": _days_left(j.deadline),
                    "score": prev[j.id].score,
                    "gaps": [g.jd_requirement for g in prev[j.id].gaps][:3],
                }
                for j in context.cached
                if j.id in prev
            ],
            "attribution": list(context.attributions),
            "excluded_restricted": excluded,
            "dismissed_count": context.dismissed_count,
            "instruction": (
                "**fresh 는 아직 평가하지 않았거나 내용이 바뀐 공고다. "
                "cached 는 지난번 평가 그대로이므로 다시 평가하지 마라** — "
                "공고 내용도 프로필도 그때와 같다. 점수를 그대로 쓰면 된다.\n"
                "fresh 를 평가하려면 job_requirements(job_ids) 로 요건을 가져와라. "
                "제목·기관·직무분야·학력만 보고 명백히 맞지 않는 것은 "
                "요건을 가져오지 말고 넘겨라 — 그게 이 2단계의 목적이다.\n"
                "평가 시 evidence_facts 의 fact_id 를 근거로 인용하고, "
                "unverified 표시가 있는 사실은 확정적으로 쓰지 마라.\n"
                "평가를 마치면 match_save 로 반드시 저장하라. "
                "저장해야 다음 실행에서 cached 로 넘어가 재평가를 건너뛴다."
            ),
        }

    async def job_detail(job_id: int) -> dict[str, Any]:
        job = await queries.detail(job_id)
        if job is None:
            return {"error": f"공고를 찾을 수 없다: job_id={job_id}"}
        return {"job": _full(job), "attribution": list(attributions_for((job,)))}

    async def job_mark(
        job_id: int, status: str, note: str | None = None
    ) -> dict[str, Any]:
        marked = await matcher.mark(job_id, InterestStatus(status), note=note)
        job = await queries.detail(job_id)
        return {
            "job_id": marked.job_id,
            "title": job.title if job else None,
            "status": str(marked.status),
            "note": marked.note,
            "effect": (
                "앞으로 추천에서 제외된다"
                if marked.status.hides_from_recommendations
                else "추천 목록에 계속 표시된다"
            ),
        }

    async def job_list(status: str | None = None) -> dict[str, Any]:
        statuses = (InterestStatus(status),) if status else ()
        marks = await matcher.marked(statuses)
        items = []
        for m in marks:
            job = await queries.detail(m.job_id)
            items.append(
                {
                    "job_id": m.job_id,
                    "status": str(m.status),
                    "note": m.note,
                    "title": job.title if job else "(공고 없음)",
                    "company": job.company if job else None,
                    "deadline": job.deadline.isoformat() if job and job.deadline else None,
                    "days_left": _days_left(job.deadline) if job else None,
                    "url": job.url if job else None,
                }
            )
        return {"count": len(items), "jobs": items}

    async def match_save(scores: list[dict[str, Any]]) -> dict[str, Any]:
        parsed = [
            ScoredJob(
                job_id=int(s["job_id"]),
                score=int(s["score"]),
                matched=tuple(
                    Evidence(m.get("jd_req", ""), int(m.get("fact_id", 0)))
                    for m in (s.get("matched") or [])
                ),
                gaps=tuple(
                    Gap(
                        g.get("jd_req", ""),
                        Severity(g.get("severity", "medium")),
                        g.get("suggestion", ""),
                    )
                    for g in (s.get("gaps") or [])
                ),
                job_hash=s.get("job_hash"),
            )
            for s in scores
        ]
        run_id = await matcher.save_scores(
            parsed, criteria=MatchFilter.for_newgrad_intern()
        )
        return {
            "run_id": run_id,
            "saved": len(parsed),
            "note": "다음 jobs_match 에서 previous_score 로 비교된다",
        }

    async def match_history(job_id: int | None = None, limit: int = 30) -> dict[str, Any]:
        results = await queries.match_history(job_id=job_id, limit=limit)
        items = []
        for r in results:
            job = await queries.detail(r.job_id)
            items.append(
                {
                    "job_id": r.job_id,
                    "title": job.title if job else "(공고 없음)",
                    "company": job.company if job else None,
                    "score": r.score,
                    "matched_count": len(r.matched),
                    "gaps": [
                        {"jd_req": g.jd_requirement, "severity": str(g.severity)}
                        for g in r.gaps
                    ],
                }
            )
        return {"count": len(items), "results": items}

    async def job_requirements(job_ids: list[int]) -> dict[str, Any]:
        out = []
        for jid in job_ids[:12]:
            job = await queries.detail(jid)
            if job is None:
                out.append({"job_id": jid, "error": "공고를 찾을 수 없다"})
                continue
            out.append(
                {
                    "job_id": jid,
                    "title": job.title,
                    "company": job.company,
                    "content_hash": job.content_hash,
                    "requirements": list(job.requirements),
                    "preferred": list(job.preferred),
                    "education": job.education,
                    "url": job.url,
                }
            )
        return {
            "count": len(out),
            "jobs": out,
            "note": (
                "match_save 로 저장할 때 각 항목에 content_hash 를 job_hash 로 넣어라. "
                "그래야 다음 실행에서 재평가를 건너뛸 수 있다."
            ),
        }

    async def ingest_status() -> dict[str, Any]:
        status = await queries.status()
        return {
            "sources": [
                {
                    "source": s.source_id,
                    "last_fetched_at": (
                        s.last_fetched_at.isoformat() if s.last_fetched_at else None
                    ),
                    "open_count": s.open_count,
                    "failed_parse_count": s.failed_parse_count,
                }
                for s in status.values()
            ]
            or [],
            "note": "수집이 오래됐다면 추천 결과도 그만큼 오래된 것이다",
        }

    return [
        ToolSpec(
            "jobs_match",
            "사용자 프로필에 맞는 인턴·신입 공고 후보를 프로필과 함께 가져온다. "
            "**사용자가 '나한테 맞는 공고 찾아줘', '지원할 만한 거 있어?', "
            "'인턴 추천해줘' 같이 요청할 때 이것을 호출한다.** "
            "반환값은 순위가 매겨지지 않은 후보 목록이고, "
            "순위·적합도·근거·부족한 요건을 만드는 것은 너의 일이다. "
            "각 후보의 requirements 를 프로필 facts 와 대조하고, "
            "matched 에는 근거가 된 fact_id 를 반드시 포함하라. "
            "**응답은 fresh(평가 필요)와 cached(지난 평가 유효)로 나뉜다.** "
            "cached 는 공고 내용도 프로필도 그때와 같으므로 다시 평가하지 마라. "
            "fresh 를 평가하려면 job_requirements 로 요건을 따로 가져온다. "
            "기본 8건만 준다 — 사람이 한 번에 검토할 수 있는 양이다. "
            "더 필요하면 limit 를 올려 다시 부른다. "
            "자격이 제한된 공고는 기본 제외하고 excluded_restricted 로 건수를 알린다. "
            "keyword 나 location 으로 좁힐 수 있다.",
            jobs_match,
        ),
        ToolSpec(
            "jobs_search",
            "채용 공고를 조건으로 검색한다. 프로필 대조 없이 목록만 필요할 때 쓴다. "
            "사용자가 특정 기관·직무·지역의 공고를 물을 때 호출한다. "
            "프로필 기반 추천이 목적이면 jobs_search 가 아니라 jobs_match 를 쓴다. "
            "employment_type: intern/fulltime/contract, "
            "career_level: newgrad/experienced/both. "
            "기본값은 인턴 + 신입 지원 가능이고 마감된 공고는 제외한다.",
            jobs_search,
        ),
        ToolSpec(
            "job_detail",
            "공고 하나의 전체 내용(지원자격 전문, 전형방법, 우대사항, 링크)을 가져온다. "
            "사용자가 특정 공고를 자세히 보고 싶어 하거나, "
            "그 공고에 맞춘 자소서·지원 전략을 논의할 때 호출한다. "
            "job_id 는 jobs_match 나 jobs_search 결과에 들어 있다.",
            job_detail,
        ),
        ToolSpec(
            "job_requirements",
            "특정 공고들의 **지원자격 전문**을 가져온다. "
            "**jobs_match 의 fresh 후보 중 평가할 가치가 있는 것만 골라 호출한다.** "
            "제목·기관·직무분야만 보고 명백히 맞지 않는 공고는 여기까지 오지 말아야 한다 — "
            "요건은 공고당 200~800자라 전부 가져오면 컨텍스트를 낭비한다. "
            "응답의 content_hash 를 match_save 에 job_hash 로 넘겨야 "
            "다음 실행에서 재평가를 건너뛸 수 있다.",
            job_requirements,
        ),
        ToolSpec(
            "job_mark",
            "공고에 대한 사용자의 입장을 기록한다. "
            "**사용자가 '거기 지원했어', '이건 관심 없어', '이건 저장해둬', "
            "'거기 떨어졌어', '합격했어' 라고 할 때 호출한다.** "
            "status: saved(관심/스크랩) / applied(지원함) / "
            "not_interested(관심 없음 → 추천에서 제외) / rejected(불합격) / accepted(합격). "
            "not_interested 만 추천에서 빠지고 나머지는 목록에 남는다 — "
            "지원한 곳을 지우면 현황을 볼 수 없기 때문이다. "
            "note 에 마감일이나 준비 상황을 적어둘 수 있다.",
            job_mark,
        ),
        ToolSpec(
            "job_list",
            "사용자가 표시해 둔 공고 목록을 본다. "
            "'내가 지원한 곳', '스크랩한 거 보여줘', '지원 현황' 같은 요청에 호출한다. "
            "status 로 좁힐 수 있다(saved/applied/not_interested/rejected/accepted). "
            "생략하면 표시된 것 전부를 보여준다.",
            job_list,
        ),
        ToolSpec(
            "match_save",
            "jobs_match 로 평가한 결과를 저장한다. "
            "**jobs_match 로 순위를 매긴 뒤 반드시 호출하라.** "
            "저장하지 않으면 다음에 같은 공고를 평가할 때 비교 기준이 없어 "
            "점수가 매번 달라지는 것을 사용자가 알 수 없다. "
            "scores 는 [{job_id, score, job_hash, matched:[{jd_req, fact_id}], "
            "gaps:[{jd_req, severity, suggestion}]}] 형식이다. "
            "**job_hash 는 job_requirements 응답의 content_hash 를 그대로 넣어라** — "
            "이게 있어야 다음 실행에서 이 공고가 cached 로 분류돼 재평가를 건너뛴다.",
            match_save,
        ),
        ToolSpec(
            "match_history",
            "과거 매칭 평가 기록을 조회한다. "
            "'전에 추천받은 거 보여줘', '이 공고 지난번엔 몇 점이었어?', "
            "'내 부족한 점이 나아졌나' 같은 요청에 호출한다. "
            "job_id 를 주면 그 공고의 점수 변화만 본다.",
            match_history,
        ),
        ToolSpec(
            "ingest_status",
            "채용 공고 수집이 마지막으로 언제 돌았고 현재 몇 건이 살아 있는지 확인한다. "
            "사용자가 '공고가 왜 없지?', '최신 정보야?' 라고 묻거나 "
            "추천 결과가 비어 있을 때 호출해 데이터 신선도를 먼저 확인하라.",
            ingest_status,
        ),
    ]
