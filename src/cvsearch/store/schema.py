"""Database schema, applied idempotently at startup.

Tables
------
cvs       one row per uploaded file; doubles as the ingestion job queue
profiles  one structured profile per CV (JSONB + computed, filterable columns)
chunks    embedded passages (one summary chunk + one per position) per profile
"""

from __future__ import annotations

from typing import Any

import psycopg

_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS cvs (
    id            UUID PRIMARY KEY,
    filename      TEXT NOT NULL,
    content_hash  TEXT NOT NULL UNIQUE,
    content       BYTEA NOT NULL,
    status        TEXT NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued', 'processing', 'done', 'failed')),
    attempts      INT NOT NULL DEFAULT 0,
    error         TEXT,
    locked_at     TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS cvs_queue_idx ON cvs (status, created_at);

CREATE TABLE IF NOT EXISTS profiles (
    cv_id               UUID PRIMARY KEY REFERENCES cvs(id) ON DELETE CASCADE,
    data                JSONB NOT NULL,
    full_name           TEXT NOT NULL,
    years_of_experience DOUBLE PRECISION NOT NULL,
    experience_basis    TEXT NOT NULL,
    seniority           TEXT,
    sector_years        JSONB NOT NULL,
    search_text         TEXT NOT NULL,
    tsv                 TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', search_text)) STORED
);
CREATE INDEX IF NOT EXISTS profiles_tsv_idx ON profiles USING gin (tsv);

CREATE TABLE IF NOT EXISTS chunks (
    id        BIGSERIAL PRIMARY KEY,
    cv_id     UUID NOT NULL REFERENCES cvs(id) ON DELETE CASCADE,
    kind      TEXT NOT NULL,
    text      TEXT NOT NULL,
    embedding VECTOR({dims}) NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_cv_idx ON chunks (cv_id);
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
"""


def apply_schema(conn: psycopg.Connection[Any], dimensions: int) -> None:
    """Create extensions, tables and indexes if they do not exist."""
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(727274)")  # serialise concurrent startups
        conn.execute(_SCHEMA.format(dims=int(dimensions)))
