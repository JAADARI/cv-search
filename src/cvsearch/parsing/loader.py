"""Format dispatch and image-only fallback.

Pipeline: native extraction first (cheap, deterministic); when the document
yields too little text, the pages/images are transcribed by the vision model.
"""

from __future__ import annotations

import logging
from pathlib import Path

from cvsearch.llm.client import LLMClient
from cvsearch.parsing.docx import extract_docx
from cvsearch.parsing.pdf import extract_pdf, render_pages
from cvsearch.parsing.pptx import extract_pptx
from cvsearch.parsing.types import RawDocument, UnsupportedFormatError

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx"}
_MAX_VISION_IMAGES = 6


def load_document(filename: str, data: bytes, llm: LLMClient, min_chars: int) -> RawDocument:
    """Return the text of a CV, falling back to vision for image-based files."""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(f"Unsupported file type '{suffix}'. Use PDF, DOCX or PPTX.")

    extractor = {".pdf": extract_pdf, ".docx": extract_docx, ".pptx": extract_pptx}[suffix]
    document = extractor(data)

    if len(document.text) >= min_chars:
        return document

    images = document.images or (render_pages(data) if suffix == ".pdf" else [])
    if not images:
        document.warnings.append("Very little text and no images to transcribe.")
        return document

    logger.info("vision_fallback file=%s native_chars=%d images=%d", filename, len(document.text), len(images))
    transcription = llm.transcribe(images[:_MAX_VISION_IMAGES])
    return RawDocument(
        text=f"{document.text}\n\n{transcription}".strip(),
        method=f"{document.method}+vision",
        warnings=["Text transcribed from images; verify names and dates."],
    )
