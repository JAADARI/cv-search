"""Deterministic experience computation.

Business rules (see ADR 0003):

* internships never count;
* overlapping positions are counted once (union of periods);
* a position without a start date cannot be placed and is ignored;
* an ongoing position ends at the reference date;
* a position with a start but no end and not flagged current ends at its start
  month plus one month (we only know it existed);
* when no dated position exists, the experience the CV states about itself is used;
* as a last resort, seniority (never years) is read from explicit words in the job title.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from cvsearch.domain.models import ExtractedPosition, Sector, Seniority

_DATE_RE = re.compile(r"^(\d{4})(?:-(\d{1,2}))?$")

_JUNIOR_TITLE_RE = re.compile(r"\b(junior|jr|débutant|graduate)\b", re.IGNORECASE)
_SENIOR_TITLE_RE = re.compile(r"\b(senior|sr|lead|principal|staff|head|directeur|director|directrice)\b", re.IGNORECASE)

JUNIOR_BELOW_YEARS = 2.0
SENIOR_FROM_YEARS = 5.0


@dataclass(frozen=True)
class ExperienceFigures:
    """Result of the experience computation for one profile."""

    years: float
    basis: str
    sector_years: dict[str, float]
    seniority: Seniority | None


def parse_month_index(value: str | None, *, end_of_period: bool = False) -> int | None:
    """Convert ``YYYY`` or ``YYYY-MM`` to a month index (year * 12 + month - 1).

    A bare year maps to January, or December when it closes a period.
    """
    if not value:
        return None
    match = _DATE_RE.match(value.strip())
    if not match:
        return None
    year = int(match.group(1))
    if match.group(2):
        month = int(match.group(2))
        if not 1 <= month <= 12:
            return None
    else:
        month = 12 if end_of_period else 1
    return year * 12 + month - 1


def _month_index_of(day: date) -> int:
    return day.year * 12 + day.month - 1


def position_period(position: ExtractedPosition, reference: date) -> tuple[int, int] | None:
    """Return the half-open ``[start, end)`` month interval of a position, if datable."""
    start = parse_month_index(position.start_date)
    if start is None:
        return None
    if position.is_current:
        end = _month_index_of(reference) + 1
    else:
        parsed_end = parse_month_index(position.end_date, end_of_period=True)
        end = (parsed_end + 1) if parsed_end is not None else start + 1
    if end <= start:
        return None
    return start, end


def merge_intervals(intervals: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """Union of half-open intervals, sorted and non-overlapping."""
    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def _years(intervals: Iterable[tuple[int, int]]) -> float:
    months = sum(end - start for start, end in merge_intervals(intervals))
    return round(months / 12, 1)


def seniority_for(years: float) -> Seniority:
    """Map years of experience to a seniority band."""
    if years < JUNIOR_BELOW_YEARS:
        return Seniority.JUNIOR
    if years < SENIOR_FROM_YEARS:
        return Seniority.CONFIRMED
    return Seniority.SENIOR


def seniority_from_title(title: str | None) -> Seniority | None:
    """Read a seniority band from explicit words in a job title, if any."""
    if not title:
        return None
    if _SENIOR_TITLE_RE.search(title):
        return Seniority.SENIOR
    if _JUNIOR_TITLE_RE.search(title):
        return Seniority.JUNIOR
    return None


def compute_experience(
    positions: Sequence[ExtractedPosition],
    stated_years: float | None,
    reference: date,
    current_title: str | None = None,
) -> ExperienceFigures:
    """Compute years of experience, per-sector years and seniority."""
    all_intervals: list[tuple[int, int]] = []
    by_sector: dict[Sector, list[tuple[int, int]]] = {}
    for position in positions:
        if position.is_internship:
            continue
        period = position_period(position, reference)
        if period is None:
            continue
        all_intervals.append(period)
        by_sector.setdefault(position.sector, []).append(period)

    if all_intervals:
        years = _years(all_intervals)
        return ExperienceFigures(
            years=years,
            basis="positions",
            sector_years={s.value: _years(iv) for s, iv in by_sector.items()},
            seniority=seniority_for(years),
        )
    if stated_years is not None:
        return ExperienceFigures(stated_years, "stated", {}, seniority_for(stated_years))
    title_band = seniority_from_title(current_title)
    return ExperienceFigures(0.0, "title" if title_band else "unknown", {}, title_band)
