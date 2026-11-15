"""Relevance evaluation over a small labelled set.

Each case lists, for a query, the profiles a recruiter would expect (``expected``)
and profiles that must not be returned as full matches (``forbidden``). An empty
``expected`` means the honest answer is "no full match".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from cvsearch.search.models import SearchResponse


class Searcher(Protocol):
    def search(self, query: str, top_k: int = 5) -> SearchResponse: ...


@dataclass
class CaseResult:
    query: str
    expected: list[str]
    returned: list[str]
    recall: float
    precision_at_k: float
    forbidden_hit: list[str]
    no_match_ok: bool | None
    ok: bool


@dataclass
class EvaluationReport:
    cases: list[CaseResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.ok for c in self.cases)

    def render(self) -> str:
        lines = []
        for c in self.cases:
            flag = "PASS" if c.ok else "FAIL"
            extra = "" if c.no_match_ok is None else f" no-match-ok={c.no_match_ok}"
            lines.append(
                f"[{flag}] recall={c.recall:.2f} p@k={c.precision_at_k:.2f}{extra}  {c.query}\n"
                f"        expected={c.expected} returned={c.returned} forbidden_hit={c.forbidden_hit}"
            )
        mean_recall = sum(c.recall for c in self.cases) / max(len(self.cases), 1)
        lines.append(f"\n{sum(c.ok for c in self.cases)}/{len(self.cases)} cases passed; mean recall {mean_recall:.2f}")
        return "\n".join(lines)


def run_evaluation(searcher: Searcher, cases: list[dict[str, Any]], top_k: int = 5) -> EvaluationReport:
    report = EvaluationReport()
    for case in cases:
        response = searcher.search(case["query"], top_k)
        expected, forbidden = case.get("expected", []), set(case.get("forbidden", []))
        returned = [h.full_name for h in response.hits]
        full = [h.full_name for h in response.hits if h.fully_matching]
        found = [name for name in expected if name in returned]
        recall = len(found) / len(expected) if expected else 1.0
        precision = len(found) / len(returned) if returned and expected else 1.0
        forbidden_hit = sorted(forbidden & set(full))
        no_match_ok = (not full) if not expected else None
        ok = recall >= case.get("min_recall", 1.0) and not forbidden_hit and no_match_ok in (None, True)
        report.cases.append(
            CaseResult(case["query"], expected, returned, recall, precision, forbidden_hit, no_match_ok, ok)
        )
    return report
