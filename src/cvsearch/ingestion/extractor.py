"""LLM-based structuring of a CV's text into an ``ExtractedProfile``."""

from __future__ import annotations

import logging
from datetime import date

from cvsearch.domain.models import ExtractedProfile
from cvsearch.llm.client import LLMClient, LLMError

logger = logging.getLogger(__name__)

_MAX_CHARS = 30_000

_SYSTEM = """You extract structured data from CVs written in French or English.

Rules:
- Use ONLY information present in the CV. Never invent employers, dates, skills or degrees.
- Dates: normalise to YYYY-MM (or YYYY when only the year is given). French months: janvier=01 ... décembre=12.
  A range such as 'févr. - mai 2024' means 2024-02 to 2024-05. 'depuis/présent/present/aujourd'hui' => is_current=true.
- is_internship is true for stage, internship, alternance, apprenticeship and student placements, including
  'junior consultant' roles explicitly described as internships. Final-year projects done for a company are internships.
- Part-time or unrelated side jobs (for example a fast-food job) are still positions, with sector 'food_services'.
- sector: the sector of the employer's business, or for a consulting firm/ESN/agency the value 'consulting'
  (use the client's sector only when the CV states the person worked inside the client).
- skills: concise, de-duplicated, canonical names (for example 'Python', 'Azure', 'Generative AI').
  Include skills evidenced in the position descriptions, not only in a skills list.
- headline: one neutral sentence in English summarising the profile.
- stated_years_of_experience: only if the CV states a number (for example '3 years of experience', '2+ years').
- Positions most recent first. Keep descriptions under 40 words."""


def extract_profile(llm: LLMClient, text: str, reference: date) -> ExtractedProfile:
    """Extract a profile; falls back to minimal reasoning if the token budget is exhausted."""
    user = f'Today is {reference.isoformat()}.\n\nCV text:\n"""\n{text[:_MAX_CHARS]}\n"""'
    try:
        return llm.structured(system=_SYSTEM, user=user, schema=ExtractedProfile, reasoning_effort="low")
    except LLMError:
        logger.warning("extraction hit the token budget, retrying with minimal reasoning")
        return llm.structured(system=_SYSTEM, user=user, schema=ExtractedProfile, reasoning_effort="minimal")
