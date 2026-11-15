"""Ingestion pipeline: document -> text -> structured profile -> embeddings -> storage."""

from __future__ import annotations

import logging
from datetime import date

from cvsearch.config import Settings
from cvsearch.domain.experience import compute_experience
from cvsearch.domain.models import ExtractedProfile, Profile
from cvsearch.embeddings.base import Embedder
from cvsearch.ingestion.extractor import extract_profile
from cvsearch.llm.client import LLMClient
from cvsearch.parsing.loader import load_document
from cvsearch.store.repository import Chunk, Job, Repository

logger = logging.getLogger(__name__)


def build_search_text(
    extracted: ExtractedProfile, years: float, seniority: str | None, sector_years: dict[str, float]
) -> str:
    """Canonical text used for full-text search and the summary embedding."""
    parts = [
        extracted.full_name,
        extracted.current_title or "",
        extracted.headline,
        f"Seniority: {seniority or 'unknown'}; {years} years of experience",
        "Sectors: " + ", ".join(f"{s} ({y} y)" for s, y in sector_years.items()),
        "Skills: " + ", ".join(extracted.skills),
        "Certifications: " + ", ".join(extracted.certifications),
        "Education: " + "; ".join(e.degree for e in extracted.education),
    ]
    for p in extracted.positions:
        parts.append(f"{p.title} at {p.organisation}: {p.description} {', '.join(p.technologies)}")
    return "\n".join(x for x in parts if x.strip())


def build_chunks(profile: Profile) -> list[Chunk]:
    """One summary chunk plus one chunk per position, so queries match precise experiences."""
    e = profile.extracted
    summary = (
        f"{e.current_title or ''}. {e.headline} {profile.years_of_experience} years of experience "
        f"({profile.seniority.value if profile.seniority else 'unknown'}). Skills: {', '.join(e.skills)}."
    )
    chunks = [Chunk("summary", summary)]
    for p in e.positions:
        chunks.append(
            Chunk(
                "position",
                f"{p.title} at {p.organisation} ({p.sector.value}"
                f"{', internship' if p.is_internship else ''}). {p.description} "
                f"Technologies: {', '.join(p.technologies)}.",
            )
        )
    return chunks


class IngestionPipeline:
    """Processes one claimed job end to end."""

    def __init__(self, settings: Settings, repo: Repository, llm: LLMClient, embedder: Embedder) -> None:
        self._settings, self._repo, self._llm, self._embedder = settings, repo, llm, embedder

    def process(self, job: Job, today: date | None = None) -> Profile:
        """Parse, structure, embed and store a CV. Raises on failure (caller records it)."""
        today = today or date.today()
        document = load_document(job.filename, job.content, self._llm, self._settings.ocr_min_chars)
        if not document.text.strip():
            raise ValueError("No text could be extracted from this file")
        extracted = extract_profile(self._llm, document.text, today)
        figures = compute_experience(
            extracted.positions, extracted.stated_years_of_experience, today, extracted.current_title
        )
        profile = Profile(
            cv_id=str(job.cv_id),
            source_filename=job.filename,
            extracted=extracted,
            years_of_experience=figures.years,
            experience_basis=figures.basis,
            sector_years=figures.sector_years,
            seniority=figures.seniority,
            search_text=build_search_text(
                extracted, figures.years, figures.seniority.value if figures.seniority else None, figures.sector_years
            ),
        )
        chunks = build_chunks(profile)
        vectors = self._embedder.embed_passages([c.text for c in chunks])
        self._repo.save_profile(profile, chunks, vectors)
        logger.info(
            "ingested cv=%s name=%s method=%s years=%s", job.cv_id, extracted.full_name, document.method, figures.years
        )
        return profile
