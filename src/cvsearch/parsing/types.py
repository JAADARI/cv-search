"""Types shared by the document extractors."""

from __future__ import annotations

from dataclasses import dataclass, field

from cvsearch.llm.client import ImageInput


class UnsupportedFormatError(ValueError):
    """Raised for file types the system cannot read."""


@dataclass
class RawDocument:
    """Text pulled natively from a file, plus images kept for a vision fallback."""

    text: str
    images: list[ImageInput] = field(default_factory=list)
    method: str = "native"
    warnings: list[str] = field(default_factory=list)
