"""PostgreSQL access: the job queue, profiles and vector/lexical retrieval.

All SQL lives here so the rest of the code base stays storage-agnostic.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from cvsearch.domain.models import Profile
from cvsearch.store.schema import apply_schema

STALE_JOB_MINUTES = 10  # a 'processing' job older than this is considered crashed


@dataclass(frozen=True)
class Job:
    """An ingestion job claimed from the queue."""

    cv_id: uuid.UUID
    filename: str
    content: bytes
    attempts: int


@dataclass(frozen=True)
class Chunk:
    """A passage to embed and store."""

    kind: str
    text: str


@dataclass(frozen=True)
class Retrieved:
    """A candidate returned by retrieval, with the evidence that surfaced it."""

    cv_id: str
    vector_rank: int | None
    lexical_rank: int | None
    best_chunk: str | None
    rrf_score: float


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vector) + "]"


class Repository:
    """Storage facade over a psycopg connection pool."""

    def __init__(self, database_url: str, dimensions: int) -> None:
        self._pool: ConnectionPool[Connection[DictRow]] = ConnectionPool(
            database_url, min_size=1, max_size=8, kwargs={"row_factory": dict_row}, open=True
        )
        with self._pool.connection() as conn:
            apply_schema(conn, dimensions)

    def close(self) -> None:
        self._pool.close()

    # ---- queue -----------------------------------------------------------------
    def enqueue(self, filename: str, content: bytes) -> tuple[uuid.UUID, bool]:
        """Queue a CV. Returns ``(cv_id, created)``; identical content is a no-op."""
        digest = hashlib.sha256(content).hexdigest()
        new_id = uuid.uuid4()
        with self._pool.connection() as conn:
            row = conn.execute(
                """INSERT INTO cvs (id, filename, content_hash, content) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (content_hash) DO NOTHING RETURNING id""",
                (new_id, filename, digest, content),
            ).fetchone()
            if row:
                return row["id"], True
            existing = conn.execute("SELECT id FROM cvs WHERE content_hash = %s", (digest,)).fetchone()
            return existing["id"], False  # type: ignore[index]

    def claim_next(self) -> Job | None:
        """Atomically claim the oldest queued (or crashed) job; safe with many workers."""
        with self._pool.connection() as conn:
            row = conn.execute(
                f"""UPDATE cvs SET status = 'processing', attempts = attempts + 1,
                           locked_at = now(), updated_at = now()
                    WHERE id = (
                        SELECT id FROM cvs
                        WHERE status = 'queued'
                           OR (status = 'processing' AND locked_at < now() - interval '{STALE_JOB_MINUTES} minutes')
                        ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
                    RETURNING id, filename, content, attempts"""
            ).fetchone()
        if not row:
            return None
        return Job(row["id"], row["filename"], bytes(row["content"]), row["attempts"])

    def fail(self, cv_id: uuid.UUID, error: str, *, final: bool) -> None:
        """Record a failure; non-final failures return the job to the queue."""
        status = "failed" if final else "queued"
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE cvs SET status = %s, error = %s, updated_at = now() WHERE id = %s",
                (status, error[:2000], cv_id),
            )

    def retry(self, cv_id: uuid.UUID) -> bool:
        """Re-queue a failed CV with a fresh attempt budget."""
        with self._pool.connection() as conn:
            cur = conn.execute(
                "UPDATE cvs SET status='queued', attempts=0, error=NULL, updated_at=now() "
                "WHERE id=%s AND status='failed'",
                (cv_id,),
            )
            return cur.rowcount > 0

    def cv_status(self, cv_id: uuid.UUID) -> dict[str, Any] | None:
        with self._pool.connection() as conn:
            return conn.execute(
                "SELECT id, filename, status, attempts, error, created_at, updated_at FROM cvs WHERE id=%s",
                (cv_id,),
            ).fetchone()

    def list_cvs(self) -> list[dict[str, Any]]:
        with self._pool.connection() as conn:
            return conn.execute(
                """SELECT c.id, c.filename, c.status, c.error, p.full_name, p.seniority,
                          p.years_of_experience, c.created_at
                   FROM cvs c LEFT JOIN profiles p ON p.cv_id = c.id ORDER BY c.created_at DESC"""
            ).fetchall()

    # ---- profiles --------------------------------------------------------------
    def save_profile(self, profile: Profile, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """Persist profile and chunks, and mark the CV done, in one transaction."""
        with self._pool.connection() as conn, conn.transaction():
            cv_id = uuid.UUID(profile.cv_id)
            conn.execute("DELETE FROM profiles WHERE cv_id = %s", (cv_id,))
            conn.execute("DELETE FROM chunks WHERE cv_id = %s", (cv_id,))
            conn.execute(
                """INSERT INTO profiles (cv_id, data, full_name, years_of_experience, experience_basis,
                                         seniority, sector_years, search_text)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    cv_id,
                    Jsonb(json.loads(profile.model_dump_json())),
                    profile.extracted.full_name,
                    profile.years_of_experience,
                    profile.experience_basis,
                    profile.seniority.value if profile.seniority else None,
                    Jsonb(profile.sector_years),
                    profile.search_text,
                ),
            )
            for chunk, vector in zip(chunks, vectors, strict=True):
                conn.execute(
                    "INSERT INTO chunks (cv_id, kind, text, embedding) VALUES (%s, %s, %s, %s::vector)",
                    (cv_id, chunk.kind, chunk.text, _vector_literal(vector)),
                )
            conn.execute("UPDATE cvs SET status='done', error=NULL, updated_at=now() WHERE id=%s", (cv_id,))

    def get_profiles(self, cv_ids: list[str]) -> dict[str, Profile]:
        if not cv_ids:
            return {}
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT cv_id, data FROM profiles WHERE cv_id = ANY(%s)", ([uuid.UUID(i) for i in cv_ids],)
            ).fetchall()
        return {str(r["cv_id"]): Profile.model_validate(r["data"]) for r in rows}

    def delete_cv(self, cv_id: uuid.UUID) -> bool:
        with self._pool.connection() as conn:
            return conn.execute("DELETE FROM cvs WHERE id = %s", (cv_id,)).rowcount > 0

    # ---- retrieval -------------------------------------------------------------
    def retrieve(self, query_vector: list[float], lexical_query: str, limit: int) -> list[Retrieved]:
        """Hybrid retrieval: vector (best chunk per CV) and lexical, fused with RRF (k=60)."""
        with self._pool.connection() as conn:
            vec_rows = conn.execute(
                """SELECT cv_id, text, dist FROM (
                       SELECT DISTINCT ON (c.cv_id) c.cv_id, c.text, c.embedding <=> %s::vector AS dist
                       FROM chunks c JOIN cvs v ON v.id = c.cv_id AND v.status = 'done'
                       ORDER BY c.cv_id, dist) t
                   ORDER BY dist LIMIT %s""",
                (_vector_literal(query_vector), limit * 3),
            ).fetchall()
            lex_rows = (
                conn.execute(
                    """SELECT cv_id FROM profiles
                   WHERE tsv @@ to_tsquery('simple', %s)
                   ORDER BY ts_rank_cd(tsv, to_tsquery('simple', %s)) DESC LIMIT %s""",
                    (lexical_query, lexical_query, limit * 3),
                ).fetchall()
                if lexical_query
                else []
            )

        scores: dict[str, Retrieved] = {}
        for rank, row in enumerate(vec_rows, start=1):
            cid = str(row["cv_id"])
            scores[cid] = Retrieved(cid, rank, None, row["text"], 1 / (60 + rank))
        for rank, row in enumerate(lex_rows, start=1):
            cid = str(row["cv_id"])
            prior = scores.get(cid)
            if prior:
                scores[cid] = Retrieved(
                    cid, prior.vector_rank, rank, prior.best_chunk, prior.rrf_score + 1 / (60 + rank)
                )
            else:
                scores[cid] = Retrieved(cid, None, rank, None, 1 / (60 + rank))
        return sorted(scores.values(), key=lambda r: r.rrf_score, reverse=True)[:limit]
