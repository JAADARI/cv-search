"""Logging setup shared by all entry points."""

from __future__ import annotations

import logging


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for noisy in ("httpx", "httpcore", "openai", "pdfminer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
