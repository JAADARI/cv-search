"""Queue worker: claims jobs from PostgreSQL and runs the pipeline."""

from __future__ import annotations

import logging
import time

from cvsearch.config import Settings
from cvsearch.ingestion.pipeline import IngestionPipeline
from cvsearch.store.repository import Repository

logger = logging.getLogger(__name__)


def run_once(settings: Settings, repo: Repository, pipeline: IngestionPipeline) -> bool:
    """Process at most one job. Returns True if a job was handled."""
    job = repo.claim_next()
    if job is None:
        return False
    try:
        pipeline.process(job)
    except Exception as exc:
        final = job.attempts >= settings.max_ingestion_attempts
        logger.exception("ingestion failed cv=%s attempt=%d final=%s", job.cv_id, job.attempts, final)
        repo.fail(job.cv_id, f"{type(exc).__name__}: {exc}", final=final)
    return True


def run_forever(settings: Settings, repo: Repository, pipeline: IngestionPipeline, poll_seconds: float = 2.0) -> None:
    """Poll the queue until interrupted."""
    logger.info("worker started")
    while True:
        if not run_once(settings, repo, pipeline):
            time.sleep(poll_seconds)
