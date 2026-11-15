from datetime import date

import pytest

from cvsearch.domain.experience import compute_experience, merge_intervals, parse_month_index
from cvsearch.domain.models import ExtractedPosition, Sector, Seniority

REF = date(2026, 1, 15)


def pos(start, end=None, *, current=False, intern=False, sector=Sector.CONSULTING):
    return ExtractedPosition(
        title="t",
        organisation="o",
        start_date=start,
        end_date=end,
        is_current=current,
        is_internship=intern,
        sector=sector,
        description="d",
        technologies=[],
    )


def test_internships_are_excluded():
    result = compute_experience([pos("2020-01", "2020-06", intern=True)], None, REF)
    assert result.years == 0.0
    assert result.basis == "unknown"


def test_overlapping_positions_count_once():
    positions = [pos("2020-01", "2021-12"), pos("2021-01", "2022-12")]
    assert compute_experience(positions, None, REF).years == 3.0


def test_ongoing_position_runs_to_reference_date():
    result = compute_experience([pos("2024-01", current=True)], None, REF)
    assert result.years == pytest.approx(2.1, abs=0.05)


def test_sector_years_only_count_that_sector():
    positions = [
        pos("2018-01", "2019-12", sector=Sector.CONSULTING),
        pos("2020-01", "2024-12", sector=Sector.RETAIL),
    ]
    result = compute_experience(positions, None, REF)
    assert result.years == 7.0
    assert result.sector_years == {"consulting": 2.0, "retail": 5.0}


def test_stated_experience_is_used_when_nothing_is_dated():
    result = compute_experience([pos(None)], 3.0, REF)
    assert (result.years, result.basis, result.seniority) == (3.0, "stated", Seniority.CONFIRMED)


def test_year_only_dates_span_whole_years():
    assert compute_experience([pos("2019", "2020")], None, REF).years == 2.0


@pytest.mark.parametrize(
    ("years", "band"),
    [(1.9, Seniority.JUNIOR), (2.0, Seniority.CONFIRMED), (4.9, Seniority.CONFIRMED), (5.0, Seniority.SENIOR)],
)
def test_seniority_bands(years, band):
    assert compute_experience([], years, REF).seniority == band


@pytest.mark.parametrize("raw", [None, "", "soon", "2020-13"])
def test_unparseable_dates_are_ignored(raw):
    assert parse_month_index(raw) is None


def test_merge_intervals_joins_touching_periods():
    assert merge_intervals([(0, 5), (5, 8), (10, 12)]) == [(0, 8), (10, 12)]


def test_seniority_falls_back_to_the_job_title_without_inventing_years():
    result = compute_experience([pos(None)], None, REF, current_title="Junior Data Engineer")
    assert (result.years, result.basis, result.seniority) == (0.0, "title", Seniority.JUNIOR)


def test_title_without_a_seniority_word_stays_unknown():
    assert compute_experience([], None, REF, current_title="Data Scientist").seniority is None
