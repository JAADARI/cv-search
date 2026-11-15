"""Schemas for query understanding, grading and API results."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from cvsearch.domain.models import Sector, Seniority


class Verdict(StrEnum):
    MET = "met"
    PARTIAL = "partial"
    NOT_MET = "not_met"


class Criterion(BaseModel):
    """One requirement of the HR query, as understood by the LLM."""

    label: str = Field(description="Short, human-readable requirement, in the language of the query.")
    importance: str = Field(description="'must' for explicit requirements, 'nice' for preferences.")
    min_years_total: float | None = Field(description="Minimum total years of experience if the query states one.")
    min_years_in_sector: float | None = Field(description="Minimum years inside `sector` if the query states one.")
    sector: Sector | None = Field(description="Sector the years requirement applies to, if any.")
    seniority: Seniority | None = Field(description="Seniority band if the query says senior/confirmé/junior.")


class QueryPlan(BaseModel):
    """Structured interpretation of a natural-language query."""

    semantic_query: str = Field(
        description="The need rewritten as a dense English description of the ideal profile, including synonyms "
        "(for example chatbot -> conversational agent, LLM, RAG)."
    )
    keywords: list[str] = Field(description="3 to 8 single-word or acronym terms that should appear in a matching CV.")
    criteria: list[Criterion] = Field(description="2 to 5 requirements the profile is judged against.")


class CriterionGrade(BaseModel):
    """Grade of one criterion for one candidate."""

    criterion_id: str = Field(description="The criterion id exactly as given, for example 'C1'.")
    verdict: Verdict
    evidence: str = Field(description="Short quote or fact from the CV supporting the verdict; empty if none.")


class CandidateGrade(BaseModel):
    cv_id: str
    grades: list[CriterionGrade]
    summary: str = Field(description="One sentence on why this profile does or does not fit, in the query's language.")


class GradingBatch(BaseModel):
    candidates: list[CandidateGrade]


class CriterionResult(BaseModel):
    """Criterion outcome returned to API clients."""

    criterion: str
    verdict: Verdict
    evidence: str
    checked_by: str = Field(description="'rules' for numeric facts computed from dates, 'llm' otherwise.")


class SearchHit(BaseModel):
    """One ranked profile with its explanation."""

    cv_id: str
    full_name: str
    current_title: str | None
    seniority: Seniority | None
    years_of_experience: float
    experience_basis: str
    score: float = Field(description="Share of weighted criteria satisfied, in [0, 1].")
    fully_matching: bool = Field(description="True when every 'must' criterion is fully met.")
    unmet_musts: int = Field(description="Number of 'must' criteria with no supporting evidence.")
    summary: str
    criteria: list[CriterionResult]
    matched_passage: str | None = Field(description="Passage that surfaced this profile in semantic retrieval.")
    retrieval: dict[str, int | None]


class SearchResponse(BaseModel):
    query: str
    interpreted_as: QueryPlan
    hits: list[SearchHit]
    no_full_match: bool = Field(description="True when no profile satisfies every 'must' criterion.")
