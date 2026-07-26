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
        out["requirements"] = list(job.requirements[:BRIEF_REQUIREMENTS])
        if len(job.requirements) > BRIEF_REQUIREMENTS:
            out["requirements_truncated"] = len(job.requirements) - BRIEF_REQUIREMENTS
    if job.preferred:
        out["preferred"] = list(job.preferred[:BRIEF_REQUIREMENTS])
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
        limit: int = 25,
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
        return {
            "profile": {
                "fact_count": snapshot.fact_count,
                "facts": {
                    str(kind): [
                        {
                            "fact_id": f.id,
                            "content": f.content,
                            "evidence": f.evidence,
                        }
                        for f in facts
                    ]
                    for kind, facts in snapshot.by_kind.items()
                },
            },
            "candidate_count": len(context.jobs),
            "candidates": [
                {
                    **_brief(j),
                    **(
                        {"previous_score": prev[j.id].score}
                        if j.id in prev else {}
                    ),
                }
                for j in context.jobs
            ],
            "dismissed_count": context.dismissed_count,
            "attribution": list(context.attributions),
            "excluded_restricted": excluded,
            "excluded_note": (
                f"지원 자격이 제한된 공고 {excluded}건을 제외했다"
                " (장애인 전형·보훈 제한경쟁·사회형평 채용 등)."
                " 사용자가 해당된다면 include_restricted=true 로 다시 호출하라."
            ) if excluded else None,
            "instruction": (
                "이것은 순위가 매겨지지 않은 후보 목록이다. "
                "각 공고의 requirements 를 프로필 facts 와 대조해 "
                "적합도 점수(0~100), 충족 근거(matched), 부족한 요건(gaps)을 만들어라. "
                "matched 의 각 항목에는 근거가 된 fact_id 를 반드시 포함하라 — "
                "근거 없는 점수는 자소서에 쓸 수 없다. "
                "gaps 에는 severity(low/medium/high)와 구체적인 보완 제안을 넣어라. "
                "상위 5개 정도만 자세히 설명하고 나머지는 간단히 언급하라. "
                "**평가를 마치면 match_save 로 점수를 반드시 저장하라** — "
                "저장하지 않으면 다음에 같은 공고를 볼 때 비교할 기준이 없다. "
                "previous_score 가 있는 후보는 지난번 평가 결과이므로 "
                "점수가 크게 달라졌다면 이유를 설명하라."
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
            "기본적으로 지원 자격이 제한된 공고(장애인 전형·보훈 제한경쟁 등)는 제외하고 "
            "몇 건이 제외됐는지 excluded_restricted 로 알려준다. "
            "사용자가 해당 자격을 갖고 있다면 include_restricted=true 로 다시 호출하라. "
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
            "scores 는 [{job_id, score, matched:[{jd_req, fact_id}], "
            "gaps:[{jd_req, severity, suggestion}]}] 형식이다.",
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
