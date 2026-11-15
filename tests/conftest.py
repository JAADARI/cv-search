"""Shared fixtures: embedded PostgreSQL and deterministic fakes for LLM and embeddings."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterator

import pgserver
import pytest
from pydantic import BaseModel

from cvsearch.config import Settings
from cvsearch.domain.models import ExtractedEducation, ExtractedPosition, ExtractedProfile, Sector

DIMS = 64


class FakeEmbedder:
    """Bag-of-words hashing embedder: deterministic, and similar texts land close together."""

    def _vec(self, text: str) -> list[float]:
        vec = [0.0] * DIMS
        for token in re.findall(r"[a-zà-ÿ0-9+#]+", text.lower()):
            vec[int(hashlib.md5(token.encode()).hexdigest(), 16) % DIMS] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class FakeLLM:
    """Replays canned structured answers, keyed by schema name, and records calls."""

    def __init__(self) -> None:
        self.answers: dict[str, BaseModel] = {}
        self.calls: list[str] = []

    def structured(self, *, system: str, user: str, schema: type[BaseModel], **_: object) -> BaseModel:
        self.calls.append(schema.__name__)
        answer = self.answers[schema.__name__]
        return answer.model_copy(deep=True)

    def transcribe(self, images: list[object]) -> str:  # pragma: no cover - not used by default
        return "transcribed"


def make_position(**kw: object) -> ExtractedPosition:
    base: dict[str, object] = {
        "title": "Data Engineer",
        "organisation": "Acme",
        "start_date": "2019-01",
        "end_date": "2024-01",
        "is_current": False,
        "is_internship": False,
        "sector": Sector.CONSULTING,
        "description": "Built data platforms on Azure.",
        "technologies": ["Azure", "Python"],
    }
    return ExtractedPosition(**{**base, **kw})  # type: ignore[arg-type]


def make_profile(name: str = "Ada Lovelace", **kw: object) -> ExtractedProfile:
    base: dict[str, object] = {
        "full_name": name,
        "current_title": "Data Engineer",
        "headline": "Data engineer building Azure platforms.",
        "stated_years_of_experience": None,
        "languages": ["French", "English"],
        "skills": ["Python", "Azure"],
        "positions": [make_position()],
        "education": [ExtractedEducation(degree="MSc", institution="X", year=2018)],
        "certifications": [],
        "email": None,
        "location": "Paris",
    }
    return ExtractedProfile(**{**base, **kw})  # type: ignore[arg-type]


@pytest.fixture(scope="session")
def database_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    server = pgserver.get_server(tmp_path_factory.mktemp("pgdata"))
    yield server.get_uri()
    server.cleanup()


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(
        APIM_BASE_URL="https://example.invalid",
        APIM_SUBSCRIPTION_KEY="x",
        DATABASE_URL=database_url,
        EMBEDDING_DIMENSIONS=DIMS,
        CVSEARCH_API_KEY="secret",
        OCR_MIN_CHARS=1,
    )


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()
