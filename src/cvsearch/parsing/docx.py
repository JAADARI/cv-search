"""DOCX extraction.

``python-docx`` only exposes body paragraphs and tables. Real CVs also hide
content in text boxes and as embedded images, so we walk the XML directly:

* document order is preserved (paragraphs, tables, text boxes);
* ``mc:Fallback`` branches are skipped (Word stores each text box twice);
* a table row is rendered on one line, cells separated by `` | ``;
* embedded images are collected, deduplicated by content and ordered by
  appearance, for the vision fallback.
"""

from __future__ import annotations

import hashlib
import zipfile
from io import BytesIO

from lxml import etree
from PIL import Image

from cvsearch.llm.client import ImageInput
from cvsearch.parsing.types import RawDocument

_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
_W = f"{{{_NS['w']}}}"
_MC = f"{{{_NS['mc']}}}"
_MIN_IMAGE_BYTES = 4000  # smaller files are icons and separator lines


def _local(el: etree._Element) -> str:
    return str(etree.QName(el).localname)


def _within(node: etree._Element, ancestors: set[etree._Element]) -> bool:
    return any(a in ancestors for a in node.iterancestors())


def _paragraph_lines(p: etree._Element) -> list[str]:
    """Text of a paragraph, then the content of any text box anchored in it."""
    boxes = set(p.iter(f"{_W}txbxContent"))
    own = "".join(t.text or "" for t in p.iter(f"{_W}t") if not _within(t, boxes))
    lines = [own.strip()] if own.strip() else []
    for box in p.iter(f"{_W}txbxContent"):
        # Word stores every text box twice: modern (Choice) and legacy (Fallback). Keep one.
        if any(a.tag == f"{_MC}Fallback" for a in box.iterancestors()):
            continue
        if _within(box, boxes):  # nested box: rendered by its parent
            continue
        lines.extend(_render_children(box))
    return lines


def _render_children(parent: etree._Element) -> list[str]:
    lines: list[str] = []
    for child in parent:
        tag = _local(child)
        if tag == "p":
            lines.extend(_paragraph_lines(child))
        elif tag == "tbl":
            for row in child.iter(f"{_W}tr"):
                cells = []
                for cell in row.findall(f"{_W}tc"):
                    cell_text = " / ".join(_render_children(cell))
                    if cell_text:
                        cells.append(cell_text)
                if cells:
                    lines.append(" | ".join(cells))
        elif tag in {"sdt", "sdtContent", "AlternateContent", "Choice", "customXml"}:
            lines.extend(_render_children(child))
    return lines


def _embedded_images(archive: zipfile.ZipFile, document: etree._Element) -> list[ImageInput]:
    rels = etree.fromstring(archive.read("word/_rels/document.xml.rels"))
    targets = {r.get("Id"): r.get("Target") for r in rels.findall("rel:Relationship", _NS)}
    seen: set[str] = set()
    images: list[ImageInput] = []
    for blip in document.iter(f"{{{_NS['a']}}}blip"):
        target = targets.get(blip.get(f"{{{_NS['r']}}}embed"))
        if not target or not target.startswith("media/"):
            continue
        raw = archive.read(f"word/{target}")
        digest = hashlib.sha256(raw).hexdigest()
        if digest in seen or len(raw) < _MIN_IMAGE_BYTES:
            continue
        seen.add(digest)
        buffer = BytesIO()
        Image.open(BytesIO(raw)).convert("RGB").save(buffer, format="PNG")
        images.append(ImageInput(buffer.getvalue()))
    return images


def extract_docx(data: bytes) -> RawDocument:
    """Extract text (and images for the fallback) from a DOCX file."""
    with zipfile.ZipFile(BytesIO(data)) as archive:
        document = etree.fromstring(archive.read("word/document.xml"))
        body = document.find(f"{_W}body")
        lines = _render_children(body) if body is not None else []
        images = _embedded_images(archive, document)
        for part in sorted(n for n in archive.namelist() if n.startswith("word/header")):
            header = etree.fromstring(archive.read(part))
            lines = _render_children(header) + lines
    return RawDocument(text="\n".join(lines).strip(), images=images, method="docx-native")
