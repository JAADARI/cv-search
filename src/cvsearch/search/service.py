"""Search orchestration: understand -> retrieve -> verify -> rank -> explain.

Why not just vector search? Vector similarity answers "which CVs talk about this",
not "which candidate has 10+ years in consulting". So the LLM turns the query into
explicit criteria, hybrid retrieval gathers a candidate pool, numeric criteria are
verified deterministically from computed experience figures, the remaining ones are
graded by the LLM with a quoted evidence, and the ranking reflects criterion
satisfaction first and retrieval relevance second.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor

from cvsearch.config import Settings
from cvsearch.domain.models import Profile
from cvsearch.embeddings.base import Embedder
from cvsearch.llm.client import LLMClient
from cvsearch.search.models import (
    CandidateGrade,
    Criterion,
    CriterionResult,
    GradingBatch,
    QueryPlan,
    SearchHit,
    SearchResponse,
    Verdict,
)
from cvsearch.store.repository import Repository, Retrieved

logger = logging.getLogger(__name__)

_GRADING_BATCH = 4
_WEIGHT = {Verdict.MET: 1.0, Verdict.PARTIAL: 0.5, Verdict.NOT_MET: 0.0}

_PLAN_SYSTEM = """You translate an HR recruiter's request (French or English) into a search plan.
- semantic_query: rewrite as a dense English description of the ideal profile; add synonyms and related tools.
- keywords: terms likely to be literally present in matching CVs (acronyms and tool names work best).
- criteria: 2 to 5 distinct requirements. Mark explicit requirements 'must', preferences 'nice'.
  Topical criteria (role, skills, domain) leave min_years_total, min_years_in_sector, sector and seniority null.
  Put each numeric or seniority constraint stated in the request in its OWN criterion, with only that field set
  ('au moins 10 ans dans le conseil' => label 'Au moins 10 ans dans le conseil', min_years_in_sector=10,
  sector=consulting; 'senior' => label 'Niveau senior', seniority=senior). Never invent constraints or numbers.
  Never set seniority for a job title such as 'Directeur': the title itself is a topical criterion."""

_GRADE_SYSTEM = """You grade candidate profiles against criteria for an HR recruiter.
For every candidate and every criterion return a verdict:
- met: clear evidence in the profile; partial: related or weaker evidence; not_met: no evidence.
Evidence must be a short quote or fact taken from the profile. Do not infer skills the profile does not show.
Facts marked [computed] are authoritative; do not recompute durations. Write summaries in the language of the query.
Return one entry per candidate (exact cv_id) and one grade per criterion (criterion id C1, C2...)."""


def _lexical_query(keywords: list[str]) -> str:
    """Build a safe OR tsquery from free-form keywords."""
    tokens = {t.lower() for kw in keywords for t in re.findall(r"[\w+#.-]+", kw) if len(t) > 1}
    return " | ".join(f"{t.replace(chr(39), '')}:*" for t in sorted(tokens))


def _numeric_checks(profile: Profile, criterion: Criterion) -> list[tuple[bool, str]]:
    """Deterministic checks for the numeric/seniority parts of a criterion."""
    checks: list[tuple[bool, str]] = []
    if criterion.min_years_total is not None:
        ok = profile.years_of_experience >= criterion.min_years_total
        checks.append(
            (ok, f"{profile.years_of_experience} years of experience [computed] (needs {criterion.min_years_total}+)")
        )
    if criterion.min_years_in_sector is not None and criterion.sector is not None:
        have = profile.sector_years.get(criterion.sector.value, 0.0)
        ok = have >= criterion.min_years_in_sector
        checks.append(
            (ok, f"{have} years in {criterion.sector.value} [computed] (needs {criterion.min_years_in_sector}+)")
        )
    if criterion.seniority is not None:
        have_band = profile.seniority.value if profile.seniority else "unknown"
        ok = profile.seniority == criterion.seniority
        checks.append((ok, f"seniority {have_band} (needs {criterion.seniority.value})"))
    return checks


def _profile_digest(profile: Profile) -> str:
    """Compact, evidence-rich rendering of a profile for the grader."""
    e = profile.extracted
    lines = [
        f"cv_id: {profile.cv_id}",
        f"name: {e.full_name} | title: {e.current_title}",
        f"[computed] years of experience excluding internships: {profile.years_of_experience} "
        f"({profile.experience_basis}); by sector: {profile.sector_years or 'n/a'}; seniority: "
        f"{profile.seniority.value if profile.seniority else 'unknown'}",
        f"skills: {', '.join(e.skills[:40])}",
        f"certifications: {', '.join(e.certifications)}",
    ]
    for p in e.positions[:8]:
        kind = "internship" if p.is_internship else "position"
        lines.append(
            f"- {kind}: {p.title} @ {p.organisation} [{p.sector.value}] {p.start_date}..{p.end_date or 'now'}: "
            f"{p.description} ({', '.join(p.technologies[:10])})"
        )
    return "\n".join(lines)


class SearchService:
    """Natural-language profile search with explanations."""

    def __init__(self, settings: Settings, repo: Repository, llm: LLMClient, embedder: Embedder) -> None:
        self._settings, self._repo, self._llm, self._embedder = settings, repo, llm, embedder

    def search(self, query: str, top_k: int = 5) -> SearchResponse:
        plan = self._llm.structured(
            system=_PLAN_SYSTEM, user=f"Request: {query}", schema=QueryPlan, reasoning_effort="minimal"
        )
        pool = self._repo.retrieve(
            self._embedder.embed_query(plan.semantic_query),
            _lexical_query(plan.keywords),
            self._settings.candidate_pool_size,
        )
        profiles = self._repo.get_profiles([r.cv_id for r in pool])
        retrieved = [r for r in pool if r.cv_id in profiles]
        llm_grades = self._grade(query, plan, [profiles[r.cv_id] for r in retrieved])

        hits = [self._build_hit(r, profiles[r.cv_id], plan, llm_grades.get(r.cv_id)) for r in retrieved]
        # Unmet hard requirements outweigh a high partial score; retrieval rank breaks ties.
        hits.sort(
            key=lambda h: (h.fully_matching, -h.unmet_musts, h.score, -(h.retrieval["vector_rank"] or 99)),
            reverse=True,
        )
        top = hits[:top_k]
        return SearchResponse(
            query=query, interpreted_as=plan, hits=top, no_full_match=not any(h.fully_matching for h in top)
        )

    def _grade(self, query: str, plan: QueryPlan, profiles: list[Profile]) -> dict[str, CandidateGrade]:
        """Grade all candidates, in parallel batches that fit the gateway's output cap."""
        criteria_text = "\n".join(f"C{i}: {c.label} [{c.importance}]" for i, c in enumerate(plan.criteria, start=1))
        batches = [profiles[i : i + _GRADING_BATCH] for i in range(0, len(profiles), _GRADING_BATCH)]

        def run(batch: list[Profile]) -> list[CandidateGrade]:
            user = f"Request: {query}\n\nCriteria:\n{criteria_text}\n\nCandidates:\n\n" + "\n\n".join(
                _profile_digest(p) for p in batch
            )
            return self._llm.structured(
                system=_GRADE_SYSTEM, user=user, schema=GradingBatch, reasoning_effort="minimal"
            ).candidates

        with ThreadPoolExecutor(max_workers=3) as pool:
            return {g.cv_id: g for result in pool.map(run, batches) for g in result}

    def _build_hit(
        self, retrieved: Retrieved, profile: Profile, plan: QueryPlan, grade: CandidateGrade | None
    ) -> SearchHit:
        by_id = {g.criterion_id.strip().upper(): g for g in (grade.grades if grade else [])}
        results: list[CriterionResult] = []
        total = earned = 0.0
        unmet_musts = 0
        all_musts_met = True
        for index, criterion in enumerate(plan.criteria, start=1):
            weight = 2.0 if criterion.importance == "must" else 1.0
            checks = _numeric_checks(profile, criterion)
            if checks:
                ok = all(c[0] for c in checks)
                result = CriterionResult(
                    criterion=criterion.label,
                    verdict=Verdict.MET if ok else Verdict.NOT_MET,
                    evidence="; ".join(c[1] for c in checks),
                    checked_by="rules",
                )
            else:
                g = by_id.get(f"C{index}")
                result = CriterionResult(
                    criterion=criterion.label,
                    verdict=g.verdict if g else Verdict.NOT_MET,
                    evidence=g.evidence if g else "not graded",
                    checked_by="llm",
                )
            total += weight
            earned += weight * _WEIGHT[result.verdict]
            unmet_musts += criterion.importance == "must" and result.verdict == Verdict.NOT_MET
            musts_met = criterion.importance != "must" or result.verdict == Verdict.MET
            all_musts_met = all_musts_met and musts_met
            results.append(result)
        e = profile.extracted
        return SearchHit(
            cv_id=profile.cv_id,
            full_name=e.full_name,
            current_title=e.current_title,
            seniority=profile.seniority,
            years_of_experience=profile.years_of_experience,
            experience_basis=profile.experience_basis,
            score=round(earned / total, 3) if total else 0.0,
            fully_matching=all_musts_met,
            unmet_musts=unmet_musts,
            summary=grade.summary if grade else "",
            criteria=results,
            matched_passage=retrieved.best_chunk,
            retrieval={"vector_rank": retrieved.vector_rank, "lexical_rank": retrieved.lexical_rank},
        )
