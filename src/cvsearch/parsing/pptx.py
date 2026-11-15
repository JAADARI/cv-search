"""PPTX extraction.

CV slides are free-form canvases. Reading order is reconstructed from shape
geometry: shapes are grouped into left-to-right columns, then read top to
bottom. Speaker notes are deliberately ignored: in the provided bank they hold
a template legend (lists of functions and skills), not candidate data, and
would pollute skill search.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from io import BytesIO

from pptx import Presentation
from pptx.shapes.autoshape import Shape
from pptx.shapes.base import BaseShape
from pptx.shapes.graphfrm import GraphicFrame
from pptx.shapes.group import GroupShape

from cvsearch.parsing.types import RawDocument

_COLUMN_TOLERANCE_EMU = 600_000  # shapes whose left edges are this close share a column


def _walk(shapes: Iterable[BaseShape]) -> Iterator[BaseShape]:
    for shape in shapes:
        if isinstance(shape, GroupShape):
            yield from _walk(shape.shapes)
        else:
            yield shape


def _shape_text(shape: BaseShape) -> str:
    if isinstance(shape, GraphicFrame) and shape.has_table:
        return "\n".join(" | ".join(c.text.strip() for c in row.cells) for row in shape.table.rows)
    if isinstance(shape, Shape) and shape.has_text_frame:
        return str(shape.text_frame.text).replace("\x0b", "\n").strip()
    return ""


def extract_pptx(data: bytes) -> RawDocument:
    """Extract text from every slide in reading order."""
    presentation = Presentation(BytesIO(data))
    chunks: list[str] = []
    for slide in presentation.slides:
        items = [(s.left or 0, s.top or 0, _shape_text(s)) for s in _walk(slide.shapes)]
        items = [i for i in items if i[2]]
        columns: list[list[tuple[int, int, str]]] = []
        for item in sorted(items, key=lambda i: i[0]):
            if columns and abs(columns[-1][0][0] - item[0]) <= _COLUMN_TOLERANCE_EMU:
                columns[-1].append(item)
            else:
                columns.append([item])
        for column in columns:
            chunks.extend(text for _, _, text in sorted(column, key=lambda i: i[1]))
    return RawDocument(text="\n\n".join(chunks).strip(), images=[], method="pptx-native")
