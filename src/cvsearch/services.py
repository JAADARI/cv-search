"""Composition root: builds the object graph once per process."""

from __future__ import annotations

from dataclasses import dataclass

from cvsearch.config import Settings, get_settings
from cvsearch.embeddings.base import Embedder, build_embedder
from cvsearch.ingestion.pipeline import IngestionPipeline
from cvsearch.llm.client import LLMClient
from cvsearch.search.service import SearchService
from cvsearch.store.repository import Repository


@dataclass
class Services:
    """Everything the entry points (API, worker, CLI) need."""

    settings: Settings
    repo: Repository
    llm: LLMClient
    embedder: Embedder
    pipeline: IngestionPipeline
    search: SearchService


def build_services(settings: Settings | None = None) -> Services:
    settings = settings or get_settings()
    repo = Repository(settings.database_url, settings.embedding_dimensions)
    llm = LLMClient(settings)
    embedder = build_embedder(settings)
    return Services(
        settings=settings,
        repo=repo,
        llm=llm,
        embedder=embedder,
        pipeline=IngestionPipeline(settings, repo, llm, embedder),
        search=SearchService(settings, repo, llm, embedder),
    )
