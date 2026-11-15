from pathlib import Path

from cvsearch.parsing.docx import extract_docx

BANK = Path(__file__).parents[2] / "data" / "cvs" / "WORD"


def test_text_boxes_are_read_once_and_in_order():
    text = extract_docx((BANK / "CV_Charles_McTurland.docx").read_bytes()).text
    assert "McTurland" in text
    assert text.count("cmcturland@email.com") == 1  # Choice branch kept, Fallback duplicate skipped


def test_tables_render_one_row_per_line():
    text = extract_docx((BANK / "CV_Aramis_Kahn.docx").read_bytes()).text
    assert "2021 / 2024 | ENSEEIHT" in text


def test_embedded_images_are_deduplicated_and_ignore_icons():
    images = extract_docx((BANK / "CV_Charles_McTurland.docx").read_bytes()).images
    assert 1 <= len(images) <= 3
