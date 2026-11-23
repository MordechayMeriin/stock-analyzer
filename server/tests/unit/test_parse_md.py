import pytest

from stock_analyzer.config import Settings
from stock_analyzer.errors import ParseError
from stock_analyzer.ingest.parse_md import detect_style, parse_report
from tests.conftest import fixture_text, live_report


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


def test_style_a_absolute_pages_and_printed_numbers(style_a):
    assert [p.index for p in style_a.pages] == [*range(1, 11), *range(55, 59)]
    printed = {p.index: p.printed for p in style_a.pages}
    assert printed[2] == 1 and printed[6] == 5 and printed[56] == 55  # the footer printed 55 is on page 56
    assert style_a.numbering_restarts == []


def test_style_b_footer_numbers_and_restarts(style_b):
    by_index = {p.index: p for p in style_b.pages}
    assert by_index[1].printed is None  # the cover has no footer
    assert [by_index[i].printed for i in range(2, 7)] == [1, 2, 3, 4, 5]
    # the fixture is a composite of separate page ranges; later chapters restart their numbering
    assert style_b.numbering_restarts and all(
        by_index[i].printed is not None for i in style_b.numbering_restarts
    )
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


def test_provider_split_page_gives_no_warning():
    """El Al FY2025: Markdown pages 79-81 have no footer and page 82 prints 13 right after the
    page printing 12 — the provider split one printed page into four Markdown pages."""
    pages = ["טקסט.\n\nפרק ב | דוח הדירקטוריון\n\n12\n"]
    pages += ['תנועת הנוסעים הצפויה בנתב"ג.\n', "| שנת 2025 | 1.2 |\n| --- | --- |\n", '| סה"כ | 18.5 |\n']
    pages += ["25 תושבים יוצאים – בדרך אוויר בלבד.\n\nפרק ב | דוח הדירקטוריון\n\n13\n"]
    r = parse("\n---\n".join(pages), settings=Settings(repeated_line_min_pages=99))
    assert [p.printed for p in r.pages] == [12, None, None, None, 13]
    assert r.warnings == [] and r.numbering_restarts == []


def test_numbering_restart_recorded_not_flagged():
    pages = [f"<!-- page {i} -->\nטקסט {i}\n\n| {p} | חברה |\n" for i, p in [(1, 1), (2, 2), (3, 1), (4, 2)]]
    r = parse("".join(pages), settings=Settings(repeated_line_min_pages=99))
    assert r.numbering_restarts == [3] and r.warnings == []


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
def test_live_fy2024_printed_numbers_and_restarts():
    text, filing_id = live_report("MLTM", 2024)
    r = parse(text, 2024, filing_id)
    assert r.style == "A" and r.page_count == 180
    printed = {p.index: p.printed for p in r.pages}
    assert printed[2] == 1 and printed[56] == 55 and printed[62] == 61  # the business chapter's run
    assert r.numbering_restarts and r.numbering_restarts[0] > 62  # later chapters restart
    assert r.warnings == []


@pytest.mark.live_data
def test_live_fy2025_pages_and_printed_numbers():
    text, filing_id = live_report("MLTM", 2025)
    r = parse(text, 2025, filing_id)
    assert r.style == "B" and r.page_count == 188  # the footnote rule on page 150 is not a break
    assert {p.index: p.printed for p in r.pages}[2] == 1 and r.warnings == []


# ---------------------------------------------------------------- other issuers' layouts


def test_unterminated_table_line_is_plain_text():
    """Delek FY2025 p801: a "|" line whose block never closes the pipe (used to crash _blocks)."""
    r = parse(fixture_text("dlekg_2025_style_b.md"), fid=33037602)
    para = next(p for p in r.paragraphs if p.text.startswith("| Key audit matters"))
    assert not para.in_table
    assert "Valuation of goodwill and oil and gas assets" in para.text
    assert r.paragraphs[-1].page_index > para.page_index  # the rest of the report is still parsed


def _two_pages(first_page_tail: str) -> str:
    return f"גוף העמוד הראשון.\n\n{first_page_tail}\n---\nעמוד שני.\n\n2\n"


def test_footer_number_above_running_header():
    """El Al FY2024: the page number sits above a running chapter header."""
    r = parse(_two_pages("טקסט אחרון בעמוד . \n\n49 \n\nפרק א | תיאור עסקי התאגיד \n\n"))
    assert r.pages[0].printed == 49
    texts = [p.text for p in r.paragraphs if p.page_index == 1]
    assert texts == ["גוף העמוד הראשון.", "טקסט אחרון בעמוד ."]


def test_footer_dash_wrapped_number():
    """Rami Levy FY2025: "- 83 -"."""
    r = parse(_two_pages("לרבות הסכמים קיבוציים מיוחדים המאמצים הסכמים קיבוציים כלליים.\n\n- 83 -\n"))
    assert r.pages[0].printed == 83
    assert all("83" not in p.text for p in r.paragraphs)


def test_footer_number_at_end_of_running_header():
    """El Al FY2025: "פרק א | תיאור עסקי התאגיד 46"."""
    r = parse(_two_pages("טקסט.\n\nפרק א | תיאור עסקי התאגיד 46\n"))
    assert r.pages[0].printed == 46
    assert all("תיאור עסקי" not in p.text for p in r.paragraphs)


def test_no_footer_number_from_questionnaire_rows():
    """El Al FY2025 p265: governance questionnaire rows end with numbered cells; a wrapped row's
    continuation line ends with "| 23 |" without starting with "|"."""
    tail = (
        "|   | ✓ | בכל ישיבות ועדת הביקורת בה נכח מי שאינו רשאי להיות חבר הוועדה | 22  |\n"
        "|   | ✓ | בשנת הדיווח היו בתוקף הסדרים שקבעה ועדת הביקורת לגבי אופן הטיפול בתלונות בקשר\n"
        "לליקויים בניהול עסקי ולגבי ההגנה שתינתן לעובדים שהתלוננו כאמור. | 23  |\n\n"
        "פרק ה | פרטים נוספים על התאגיד\n"
    )
    r = parse(_two_pages(tail))
    assert r.pages[0].printed is None
    assert any(p.in_table and "| 23 |" in p.text for p in r.paragraphs)


def test_page_head_skips_logo_ocr_and_images():
    """El Al FY2025 business cover: "ELYAL", an image, "# פרק א'", then the title line."""
    r = parse(fixture_text("elal_2025_style_b.md"), fid=32839476)
    cover = r.pages[2]  # fixture page 3 = source page 3
    assert cover.head == ["פרק א'", "דוח תיאור עסקי התאגיד", 'אל על נתיבי אויר לישראל בע"מ']
    assert all("ELYAL" not in line for p in r.pages for line in p.head)


def test_page_head_is_taken_before_footer_stripping():
    r = parse(_two_pages("טקסט.\n\nפרק א | תיאור עסקי התאגיד 46\n"))
    assert r.pages[0].printed == 46
    # trailing punctuation is kept in heads ("title ." marks the end of a sentence)
    assert r.pages[0].head == ["גוף העמוד הראשון.", "טקסט.", "פרק א | תיאור עסקי התאגיד 46"]
    assert all("תיאור עסקי" not in p.text for p in r.paragraphs)  # stripped from the text
    assert r.pages[1].head == ["עמוד שני."]  # the bare footer number has no letters


def test_running_header_at_page_edges():
    """El Al: "פרק א | תיאור עסקי התאגיד" at the edge of business pages, sometimes with a number
    glued on; far below the global 30% threshold in a long report."""
    pages = []
    for i in range(1, 21):
        if i <= 5:
            top = "פרק א | תיאור עסקי התאגיד" + (f" {i + 40}" if i % 2 else "")
            pages.append(f"{top}\n\nגוף עמוד {i}.\n")
        elif i <= 8:
            pages.append(f"שורה חוזרת בשלושה עמודים\n\nגוף עמוד {i}.\n")
        else:
            pages.append(f"גוף עמוד {i}.\n")
    r = parse("\n---\n".join(pages))
    assert r.repeated_lines == []  # under the global threshold
    assert all("תיאור עסקי" not in p.text for p in r.paragraphs)
    assert [p.running_header for p in r.pages[:5]] == ["פרק א | תיאור עסקי התאגיד"] * 5
    assert sum("שורה חוזרת בשלושה עמודים" == p.text for p in r.paragraphs) == 3  # three pages: kept
    assert all(p.running_header is None for p in r.pages[5:])
    # body lines that differ only by a number are not one running line
    assert [p.text for p in r.paragraphs if p.text.startswith("גוף עמוד")] == [
        f"גוף עמוד {i}." for i in range(1, 21)
    ]


def test_running_line_min_pages_from_config():
    body = [f"כותרת רצה\n\nגוף {i}.\n" if i <= 3 else f"גוף {i}.\n" for i in range(1, 13)]
    pages = "\n---\n".join(body)  # 3 of 12 pages: under the global 30% threshold
    assert any(p.text == "כותרת רצה" for p in parse(pages).paragraphs)  # 3 pages < default 4
    r = parse(pages, settings=Settings(running_line_min_pages=3))
    assert all(p.text != "כותרת רצה" for p in r.paragraphs)
