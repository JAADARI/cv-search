"""Application settings, read from environment variables (12-factor).

Secrets are never given defaults. In Azure they are injected from Key Vault.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration for the API, worker, CLI and UI."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    # --- LLM gateway (Azure OpenAI behind API Management) ---
    apim_base_url: str = Field(alias="APIM_BASE_URL")
    apim_subscription_key: SecretStr = Field(alias="APIM_SUBSCRIPTION_KEY")
    chat_deployment: str = Field(default="gpt-5", alias="CHAT_DEPLOYMENT")
    openai_api_version: str = Field(default="2025-01-01-preview", alias="OPENAI_API_VERSION")
    # The gateway rejects any request above 4000 output tokens.
    max_completion_tokens: int = Field(default=4000, le=4000, alias="MAX_COMPLETION_TOKENS")
    llm_timeout_seconds: float = Field(default=120.0, alias="LLM_TIMEOUT_SECONDS")

    # --- Embeddings ---
    embedding_provider: Literal["azure", "local"] = Field(default="local", alias="EMBEDDING_PROVIDER")
    # Azure: endpoint/key of the Azure OpenAI resource holding the embedding deployment.
    embedding_endpoint: str | None = Field(default=None, alias="EMBEDDING_ENDPOINT")
    embedding_api_key: SecretStr | None = Field(default=None, alias="EMBEDDING_API_KEY")
    embed_deployment: str = Field(default="text-embedding-3-small", alias="EMBED_DEPLOYMENT")
    embedding_dimensions: int = Field(default=1024, alias="EMBEDDING_DIMENSIONS")
    # Local: fastembed model name; must output ``embedding_dimensions`` dimensions.
    local_embedding_model: str = Field(default="intfloat/multilingual-e5-large", alias="LOCAL_EMBEDDING_MODEL")

    # --- Storage ---
    database_url: str = Field(alias="DATABASE_URL")

    # --- Security ---
    api_key: SecretStr | None = Field(default=None, alias="CVSEARCH_API_KEY")
    ui_password: SecretStr | None = Field(default=None, alias="CVSEARCH_UI_PASSWORD")

    # --- Ingestion / search behaviour ---
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, alias="MAX_UPLOAD_BYTES")
    max_ingestion_attempts: int = Field(default=3, alias="MAX_INGESTION_ATTEMPTS")
    ocr_min_chars: int = Field(default=400, alias="OCR_MIN_CHARS")
    candidate_pool_size: int = Field(default=15, alias="CANDIDATE_POOL_SIZE")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
