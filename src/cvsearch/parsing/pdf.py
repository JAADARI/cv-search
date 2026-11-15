"""PDF text extraction with column awareness.

CVs are frequently two-column. Reading text in raw stream order interleaves the
columns, which hurts the LLM. We detect a vertical gutter (a band of x positions
no word crosses) and extract each column separately, left to right.
"""

from __future__ import annotations

import io

import pdfplumber
import pypdfium2 as pdfium

from cvsearch.llm.client import ImageInput
from cvsearch.parsing.types import RawDocument

_MIN_GUTTER_PT = 8.0  # narrowest empty band treated as a column separator
_MIN_COLUMN_SHARE = 0.18  # a column must hold at least this share of the words
_RENDER_SCALE = 1.6  # ~115 dpi: readable for the vision model, cheap in tokens


def _find_gutter(words: list[dict[str, float]], page_width: float) -> float | None:
    """Return the x position of a column gutter, or None for single-column pages."""
    if len(words) < 30:
        return None
    lo, hi = page_width * 0.2, page_width * 0.8
    occupied = [False] * int(page_width) + [False]
    for word in words:
        for x in range(int(word["x0"]), min(int(word["x1"]) + 1, len(occupied))):
            occupied[x] = True
    best: tuple[int, int] | None = None
    run_start: int | None = None
    for x in range(int(lo), int(hi) + 1):
        if not occupied[x]:
            run_start = x if run_start is None else run_start
        elif run_start is not None:
            if best is None or x - run_start > best[1] - best[0]:
                best = (run_start, x)
            run_start = None
    if best is None or best[1] - best[0] < _MIN_GUTTER_PT:
        return None
    gutter = (best[0] + best[1]) / 2
    left = sum(1 for w in words if w["x1"] <= gutter)
    right = sum(1 for w in words if w["x0"] >= gutter)
    share = min(left, right) / len(words)
    return gutter if share >= _MIN_COLUMN_SHARE else None


def _page_text(page: pdfplumber.page.Page) -> str:
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    gutter = _find_gutter(words, float(page.width))
    if gutter is None:
        return page.extract_text() or ""
    x0, top, x1, bottom = page.bbox  # the page box may not start at the origin
    columns = [
        page.crop((x0, top, gutter, bottom)),
        page.crop((gutter, top, x1, bottom)),
    ]
    return "\n\n".join((col.extract_text() or "").strip() for col in columns)


def render_pages(data: bytes, max_pages: int = 4) -> list[ImageInput]:
    """Render the first pages to PNG for the vision fallback."""
    pdf = pdfium.PdfDocument(data)
    images: list[ImageInput] = []
    for index in range(min(len(pdf), max_pages)):
        buffer = io.BytesIO()
        pdf[index].render(scale=_RENDER_SCALE).to_pil().save(buffer, format="PNG")
        images.append(ImageInput(buffer.getvalue()))
    return images


def extract_pdf(data: bytes) -> RawDocument:
    """Extract text from a PDF, keeping page images only when text is scarce."""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        text = "\n\n".join(_page_text(page) for page in pdf.pages)
    return RawDocument(text=text.strip(), images=[], method="pdf-native")
