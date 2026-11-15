"""End-to-end behaviour through the HTTP API, with a real PostgreSQL/pgvector and fake LLM/embeddings."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cvsearch.api.app import create_app
from cvsearch.config import Settings
from cvsearch.ingestion.pipeline import IngestionPipeline
from cvsearch.ingestion.worker import run_once
from cvsearch.search.models import (
    CandidateGrade,
    Criterion,
    CriterionGrade,
    GradingBatch,
    QueryPlan,
    Verdict,
)
from cvsearch.search.service import SearchService
from cvsearch.services import Services
from cvsearch.store.repository import Repository
from tests.conftest import DIMS, FakeEmbedder, FakeLLM, make_position, make_profile

pytestmark = pytest.mark.integration

BANK = Path(__file__).parents[2] / "data" / "cvs"
HEADERS = {"X-API-Key": "secret"}


@pytest.fixture
def services(settings: Settings, fake_llm: FakeLLM) -> Iterator[Services]:
    repo = Repository(settings.database_url, DIMS)
    with repo._pool.connection() as conn:
        conn.execute("TRUNCATE cvs CASCADE")
    embedder = FakeEmbedder()
    yield Services(
        settings=settings,
        repo=repo,
        llm=fake_llm,  # type: ignore[arg-type]
        embedder=embedder,
        pipeline=IngestionPipeline(settings, repo, fake_llm, embedder),  # type: ignore[arg-type]
        search=SearchService(settings, repo, fake_llm, embedder),  # type: ignore[arg-type]
    )
    repo.close()


@pytest.fixture
def client(services: Services) -> Iterator[TestClient]:
    with TestClient(create_app(lambda: services)) as c:
        yield c


def upload(client: TestClient, name: str, content: bytes, headers: dict[str, str] | None = HEADERS):
    return client.post("/cvs", files=[("files", (name, content))], headers=headers)


def drain(services: Services) -> None:
    while run_once(services.settings, services.repo, services.pipeline):
        pass


DOCX = (BANK / "WORD" / "CV_Aramis_Kahn.docx").read_bytes()


def test_requests_without_api_key_are_rejected(client: TestClient):
    assert client.get("/cvs").status_code == 401
    assert upload(client, "a.docx", DOCX, headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/health").status_code == 200  # liveness stays open


def test_unsupported_and_empty_files_are_rejected(client: TestClient):
    assert upload(client, "cv.txt", b"hello").status_code == 415
    assert upload(client, "cv.docx", b"").status_code == 400


def test_uploading_the_same_file_twice_is_a_no_op(client: TestClient):
    first = upload(client, "a.docx", DOCX).json()[0]
    second = upload(client, "renamed.docx", DOCX).json()[0]
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert second["cv_id"] == first["cv_id"]
    assert len(client.get("/cvs", headers=HEADERS).json()) == 1


def test_a_queued_cv_becomes_a_profile_with_computed_experience(
    client: TestClient, services: Services, fake_llm: FakeLLM
):
    fake_llm.answers["ExtractedProfile"] = make_profile(
        "Ada Lovelace",
        positions=[
            make_position(start_date="2015-01", end_date="2019-12"),
            make_position(start_date="2017-01", end_date="2018-12", organisation="Overlap"),
            make_position(start_date="2020-01", end_date="2020-06", is_internship=True),
        ],
    )
    cv_id = upload(client, "a.docx", DOCX).json()[0]["cv_id"]
    assert client.get(f"/cvs/{cv_id}", headers=HEADERS).json()["status"] == "queued"

    drain(services)

    assert client.get(f"/cvs/{cv_id}", headers=HEADERS).json()["status"] == "done"
    profile = client.get(f"/cvs/{cv_id}/profile", headers=HEADERS).json()
    assert profile["years_of_experience"] == 5.0  # overlap counted once, internship excluded
    assert profile["seniority"] == "senior"


def test_a_failing_cv_is_retried_then_marked_failed_and_can_be_requeued(client: TestClient, services: Services):
    # No canned answer: the fake LLM raises KeyError, standing for any extraction failure.
    cv_id = upload(client, "a.docx", DOCX).json()[0]["cv_id"]
    drain(services)
    row = client.get(f"/cvs/{cv_id}", headers=HEADERS).json()
    assert row["status"] == "failed"
    assert row["attempts"] == services.settings.max_ingestion_attempts
    assert "KeyError" in row["error"]

    assert client.post(f"/cvs/{cv_id}/retry", headers=HEADERS).status_code == 202
    assert client.get(f"/cvs/{cv_id}", headers=HEADERS).json()["status"] == "queued"


def test_search_ranks_by_criteria_and_reports_when_nobody_fully_matches(
    client: TestClient, services: Services, fake_llm: FakeLLM
):
    consultant = make_profile("Claire Consultant", positions=[make_position(start_date="2010-01", end_date="2022-12")])
    junior = make_profile(
        "Jules Junior", positions=[make_position(start_date="2024-01", end_date="2024-12")], skills=["Excel"]
    )
    for name, profile, content in [("c", consultant, DOCX + b"1"), ("j", junior, DOCX + b"2")]:
        fake_llm.answers["ExtractedProfile"] = profile
        upload(client, f"{name}.docx", content)
        drain(services)

    ids = {r["full_name"]: str(r["id"]) for r in client.get("/cvs", headers=HEADERS).json()}
    fake_llm.answers["QueryPlan"] = QueryPlan(
        semantic_query="data engineer building azure platforms",
        keywords=["azure", "platform"],
        criteria=[
            Criterion(
                label="Builds data platforms",
                importance="must",
                min_years_total=None,
                min_years_in_sector=None,
                sector=None,
                seniority=None,
            ),
            Criterion(
                label="At least 10 years of experience",
                importance="must",
                min_years_total=10,
                min_years_in_sector=None,
                sector=None,
                seniority=None,
            ),
        ],
    )
    fake_llm.answers["GradingBatch"] = GradingBatch(
        candidates=[
            CandidateGrade(
                cv_id=ids[n], summary="s", grades=[CriterionGrade(criterion_id="C1", verdict=Verdict.MET, evidence="e")]
            )
            for n in ids
        ]
    )

    body = client.post("/search", json={"query": "ingénieur data 10 ans", "top_k": 5}, headers=HEADERS).json()
    names = [h["full_name"] for h in body["hits"]]
    assert names[0] == "Claire Consultant"
    top = body["hits"][0]
    assert top["fully_matching"] is True
    assert any(c["checked_by"] == "rules" and c["verdict"] == "met" for c in top["criteria"])
    junior_hit = next(h for h in body["hits"] if h["full_name"] == "Jules Junior")
    assert junior_hit["fully_matching"] is False and junior_hit["unmet_musts"] == 1

    # Nobody has 30 years: the answer must say so instead of presenting a confident top-N.
    fake_llm.answers["QueryPlan"].criteria[1].min_years_total = 30  # type: ignore[attr-defined]
    body = client.post("/search", json={"query": "expert 30 ans"}, headers=HEADERS).json()
    assert body["no_full_match"] is True


def test_deleting_a_cv_removes_its_profile_and_search_results(
    client: TestClient, services: Services, fake_llm: FakeLLM
):
    fake_llm.answers["ExtractedProfile"] = make_profile()
    cv_id = upload(client, "a.docx", DOCX).json()[0]["cv_id"]
    drain(services)
    assert client.delete(f"/cvs/{cv_id}", headers=HEADERS).status_code == 204
    assert client.get(f"/cvs/{cv_id}/profile", headers=HEADERS).status_code == 404
    assert client.delete(f"/cvs/{cv_id}", headers=HEADERS).status_code == 404


def test_pipeline_uses_the_reference_date_for_ongoing_positions(services: Services, fake_llm: FakeLLM):
    fake_llm.answers["ExtractedProfile"] = make_profile(
        positions=[make_position(start_date="2023-01", end_date=None, is_current=True)]
    )
    job_id, _ = services.repo.enqueue("a.docx", DOCX)
    job = services.repo.claim_next()
    assert job is not None and job.cv_id == job_id
    profile = services.pipeline.process(job, today=date(2025, 12, 31))
    assert profile.years_of_experience == 3.0
