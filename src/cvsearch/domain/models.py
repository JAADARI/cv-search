"""Domain models shared across parsing, storage and search.

Two families live here:

* ``Extracted*`` models describe what the LLM reads from a CV. They contain no
  defaults so they can be used as strict structured-output schemas.
* ``Profile`` is the enriched, stored representation: the extraction plus
  figures computed deterministically (years of experience, seniority).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Sector(StrEnum):
    """Closed vocabulary of business sectors, so sector filters are reliable."""

    CONSULTING = "consulting"
    RETAIL = "retail"
    LUXURY = "luxury"
    BANKING_FINANCE = "banking_finance"
    INSURANCE = "insurance"
    TELECOM = "telecom"
    TRANSPORT_LOGISTICS = "transport_logistics"
    INDUSTRY = "industry"
    ENERGY = "energy"
    PUBLIC_SECTOR = "public_sector"
    TECH_SOFTWARE = "tech_software"
    MEDIA_ADVERTISING = "media_advertising"
    HEALTHCARE = "healthcare"
    RESEARCH_EDUCATION = "research_education"
    FOOD_SERVICES = "food_services"
    OTHER = "other"


class Seniority(StrEnum):
    """Experience band derived from years of experience."""

    JUNIOR = "junior"
    CONFIRMED = "confirmed"
    SENIOR = "senior"


class ExtractedPosition(BaseModel):
    """A position as read from the CV; dates are normalised to YYYY-MM."""

    title: str = Field(description="Job title as written on the CV.")
    organisation: str = Field(description="Employer or client organisation name.")
    start_date: str | None = Field(description="Start as YYYY-MM, or YYYY if only a year is known. Null if absent.")
    end_date: str | None = Field(description="End as YYYY-MM, or YYYY. Null if the position is ongoing OR unknown.")
    is_current: bool = Field(
        description="True when the CV says the position is ongoing (present, depuis, aujourd'hui...)."
    )
    is_internship: bool = Field(description="True for internships, stages, apprenticeships and student placements.")
    sector: Sector = Field(description="Business sector of the organisation or its clients.")
    description: str = Field(description="One or two sentences summarising the responsibilities and achievements.")
    technologies: list[str] = Field(description="Tools, languages, platforms and cloud services used in this position.")


class ExtractedEducation(BaseModel):
    """A degree or certification."""

    degree: str = Field(description="Degree or certification name.")
    institution: str | None = Field(description="School or issuing body.")
    year: int | None = Field(description="Graduation or issue year, if present.")


class ExtractedProfile(BaseModel):
    """Everything the LLM extracts from one CV."""

    full_name: str = Field(description="The candidate's full name.")
    current_title: str | None = Field(description="Most recent or headline job title.")
    headline: str = Field(description="One-sentence professional summary written from the CV content only.")
    stated_years_of_experience: float | None = Field(
        description="Years of experience the CV explicitly claims (for example '3 years of experience'). Null if none."
    )
    languages: list[str] = Field(description="Spoken languages, as names in English (for example French, English).")
    skills: list[str] = Field(description="Normalised technical and functional skills.")
    positions: list[ExtractedPosition] = Field(description="Every position, most recent first.")
    education: list[ExtractedEducation]
    certifications: list[str]
    email: str | None
    location: str | None = Field(description="City and country if present.")


class Profile(BaseModel):
    """Stored profile: extraction plus deterministic figures."""

    cv_id: str
    source_filename: str
    extracted: ExtractedProfile
    years_of_experience: float
    experience_basis: str = Field(
        description="'positions' when computed from dated positions, else 'stated' or 'unknown'."
    )
    sector_years: dict[str, float]
    seniority: Seniority | None
    search_text: str = Field(description="Canonical text that is embedded and full-text indexed.")
