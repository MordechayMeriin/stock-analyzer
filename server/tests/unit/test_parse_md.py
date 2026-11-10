import pytest

from stock_analyzer.config import Settings
from stock_analyzer.errors import ParseError
from stock_analyzer.ingest.parse_md import detect_style, parse_report
from tests.conftest import LIVE_FILINGS, fixture_text, live_report


def parse(text, fy=2025, fid=1, **kw):
    return parse_report(text, ticker="MLTM", fiscal_year=fy, filing_id=fid, **kw)


@pytest.fixture(scope="module")
def style_a():
    return parse(fixture_text("mltm_2024_style_a.md"), 2024, 63741657)


@pytest.fixture(scope="module")
def style_b():
    return parse(fixture_text("mltm_2025_style_b.md"), 2025, 32935334)


# ---------------------------------------------------------------- style detection


def test_style_a_detected(style_a):
    assert style_a.style == "A"


def test_style_b_detected(style_b):
    assert style_b.style == "B"


def test_unknown_style_fails():
    with pytest.raises(ParseError, match="page style"):
        detect_style("just text\n\nwith no page markers")


def test_table_divider_is_not_page_break():
    text = "עמוד 1\n\n| א | ב |\n| --- | --- |\n| 1 | 2 |\n\n---\n\nעמוד 2\n|---|---|\n"
    r = parse(text)
    assert r.page_count == 2
    table = next(p for p in r.paragraphs if p.in_table)
    assert table.page_index == 1 and "| --- | --- |" in table.raw


# ---------------------------------------------------------------- pages and printed numbers


def test_style_a_absolute_pages_and_offset(style_a):
    assert [p.index for p in style_a.pages] == [*range(1, 11), *range(55, 59)]
    printed = {p.index: p.printed for p in style_a.pages}
    assert printed[2] == 1 and printed[6] == 5 and printed[56] == 55  # footer "| 55 |" is on PDF page 56
    assert [(r.first_page, r.offset) for r in style_a.offset_runs] == [(1, 1)]
    assert style_a.offset_issues == [] and style_a.numbering_restarts == []


def test_style_b_footer_offset_and_restarts(style_b):
    first = style_b.offset_runs[0]
    assert first.first_page == 2 and first.offset == 1  # cover has no footer; page 2 prints 1
    by_index = {p.index: p for p in style_b.pages}
    assert by_index[1].printed is None
    # the fixture is a composite of separate page ranges, so offsets jump at its seams;
    # within the first range (source pages 1-6) the offset is constant
    assert (first.first_page, first.last_page) == (2, 6)
    risk = next(p for p in style_b.paragraphs if p.text == "22.1.2 שינויים בשערי החליפין, אינפלציה וריבית")
    assert risk.page_printed == 58  # PDF page 59 prints 58


def test_footnote_rule_is_not_a_page_break(style_b):
    # 37 source pages in the fixture; md pages 150+151 are one PDF page split by a footnote rule
    assert style_b.page_count == 36
    page = next(p for p in style_b.paragraphs if p.text.startswith('³ "הרווח הנקי לבעלי המניות'))
    before = [p for p in style_b.paragraphs if p.page_index == page.page_index and p.seq < page.seq]
    assert before, "footnotes stay on the page they annotate"
    assert page.page_printed == 4


def test_synthetic_footnote_rule():
    text = "עמוד\n\nwww.x.com | חברה | 1\n\n---\n\nגוף העמוד\n\n---\n¹ הערת שוליים\n\nwww.x.com | חברה | 2\n\n---\n\nעמוד שלישי"
    r = parse(text)
    assert r.page_count == 3
    assert [p.printed for p in r.pages] == [1, 2, None]


def test_offset_inconsistency_logged():
    pages = [
        f"<!-- page {i} -->\nטקסט {i}\n\nwww.x.com | חברה | {p} |\n"
        for i, p in [(1, 0), (2, 1), (3, 2), (4, 5), (5, 4)]
    ]
    r = parse("".join(pages), settings=Settings(repeated_line_min_pages=99))
    assert [(i.page, i.printed, i.expected_printed) for i in r.offset_issues] == [(4, 5, 3)]
    assert r.warnings == ["page 4: printed 5, expected 3"]


def test_numbering_restart_recorded_not_flagged():
    pages = [f"<!-- page {i} -->\nטקסט {i}\n\n| {p} | חברה |\n" for i, p in [(1, 1), (2, 2), (3, 1), (4, 2)]]
    r = parse("".join(pages), settings=Settings(repeated_line_min_pages=99))
    assert r.numbering_restarts == [3] and r.offset_issues == []


# ---------------------------------------------------------------- noise and paragraphs


def test_footers_and_picture_text_stripped(style_a):
    texts = [p.text for p in style_a.paragraphs]
    assert not any("| 55 |" in t or "Start of picture text" in t for t in texts)
    assert not any(t.endswith("| 5 |") for t in texts)


def test_repeated_header_removed(style_a, style_b):
    assert "דוח תקופתי לשנת 2024" in style_a.repeated_lines
    assert not any(p.text == "דוח תקופתי לשנת 2024" for p in style_a.paragraphs)
    for header in style_b.repeated_lines:
        assert not any(p.text == header for p in style_b.paragraphs)
    assert style_b.repeated_lines


def test_repeated_line_threshold_from_config():
    pages = "".join(f"<!-- page {i} -->\nכותרת חוזרת\n\nתוכן {i}\n" for i in range(1, 11))
    assert parse(pages).repeated_lines == ["כותרת חוזרת"]
    assert parse(pages, settings=Settings(repeated_line_ratio=1.0)).repeated_lines == []


def test_stable_ids_across_runs():
    text = fixture_text("mltm_2025_style_b.md")
    a = [p.pid for p in parse(text).paragraphs]
    b = [p.pid for p in parse(text).paragraphs]
    assert a == b and len(set(a)) == len(a)
    assert a[0] == "MLTM-2025-p0001-001"


def test_table_kept_as_one_paragraph(style_b):
    tables = [p for p in style_b.paragraphs if p.in_table]
    big = max(tables, key=lambda p: p.raw.count("\n"))
    assert big.raw.count("\n") >= 5 and big.raw.count("| --- |") >= 1
    assert all(line.strip() for line in big.text.split("\n"))


def test_paragraph_fields(style_b):
    p = next(p for p in style_b.paragraphs if "תלות בתקציבי המדינה" in p.text and p.heading_level)
    assert p.heading_level == 2 and p.text == "22.1.3 תלות בתקציבי המדינה"
    src = fixture_text("mltm_2025_style_b.md")
    assert src[p.char_start : p.char_end] == p.raw
    assert p.filing_id == 32935334 and p.fiscal_year == 2025 and not p.in_table
    assert [q.seq for q in style_b.paragraphs] == list(range(len(style_b.paragraphs)))


def test_split_on_blank_lines_and_headings():
    r = parse("<!-- page 1 -->\n# כותרת\nשורה אחת\nשורה שתיים\n\nפסקה שנייה\n<!-- page 2 -->\nעוד\n")
    assert [(p.text, p.heading_level) for p in r.paragraphs] == [
        ("כותרת", 1),
        ("שורה אחת שורה שתיים", 0),
        ("פסקה שנייה", 0),
        ("עוד", 0),
    ]


# ---------------------------------------------------------------- full reports (when cached)


@pytest.mark.live_data
def test_live_fy2024_offset_one_no_issues():
    r = parse(live_report(2024), 2024, LIVE_FILINGS[2024])
    assert r.style == "A" and r.page_count == 180  # the PDF has 180 pages
    assert (r.offset_runs[0].first_page, r.offset_runs[0].last_page, r.offset_runs[0].offset) == (1, 62, 1)
    assert r.offset_issues == []


@pytest.mark.live_data
def test_live_fy2025_matches_pdf_pages():
    r = parse(live_report(2025), 2025, LIVE_FILINGS[2025])
    assert r.style == "B" and r.page_count == 188  # the PDF has 188 pages
    assert r.offset_runs[0].offset == 1 and r.offset_issues == []
