"""Embedding providers behind one interface.

The provider is chosen by configuration: Azure OpenAI in the cloud, a local
open-source multilingual model for offline runs and tests. Both must return
vectors of ``settings.embedding_dimensions`` so the database schema is stable.
"""

from __future__ import annotations

from typing import Protocol

from openai import AzureOpenAI
from tenacity import retry, stop_after_attempt, wait_random_exponential

from cvsearch.config import Settings

_BATCH = 64


class Embedder(Protocol):
    """Turns text into vectors; queries and passages may be encoded differently."""

    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class AzureOpenAIEmbedder:
    """Azure OpenAI embeddings (text-embedding-3-*), shortened to the configured size."""

    def __init__(self, settings: Settings) -> None:
        if not (settings.embedding_endpoint and settings.embedding_api_key):
            raise ValueError("EMBEDDING_ENDPOINT and EMBEDDING_API_KEY are required for the azure provider")
        self._client = AzureOpenAI(
            api_version="2024-10-21",
            azure_endpoint=settings.embedding_endpoint,
            api_key=settings.embedding_api_key.get_secret_value(),
            max_retries=0,
        )
        self._deployment = settings.embed_deployment
        self._dimensions = settings.embedding_dimensions

    @retry(wait=wait_random_exponential(multiplier=1, max=20), stop=stop_after_attempt(5), reraise=True)
    def _embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(model=self._deployment, input=texts, dimensions=self._dimensions)
        return [item.embedding for item in response.data]

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), _BATCH):
            vectors.extend(self._embed(texts[start : start + _BATCH]))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]


class LocalEmbedder:
    """Local ONNX model via fastembed (multilingual-e5 by default, French and English)."""

    def __init__(self, settings: Settings) -> None:
        from fastembed import TextEmbedding  # heavy import, only when used

        self._model = TextEmbedding(model_name=settings.local_embedding_model)
        size = self._model.embedding_size
        if size != settings.embedding_dimensions:
            raise ValueError(
                f"{settings.local_embedding_model} outputs {size} dims but EMBEDDING_DIMENSIONS="
                f"{settings.embedding_dimensions}"
            )

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in vector] for vector in self._model.passage_embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return [float(x) for x in next(iter(self._model.query_embed(text)))]


def build_embedder(settings: Settings) -> Embedder:
    """Instantiate the configured embedding provider."""
    if settings.embedding_provider == "azure":
        return AzureOpenAIEmbedder(settings)
    return LocalEmbedder(settings)
