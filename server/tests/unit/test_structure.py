import logging

import pytest

from stock_analyzer.config import Settings
from stock_analyzer.ingest.parse_md import parse_report
from stock_analyzer.ingest.structure import build_structure, chapter_ordinal
from tests.conftest import LIVE_FILINGS, fixture_text, live_report


def structure_of(text, fy=2025, settings=None):
    settings = settings or Settings(repeated_line_min_pages=999)
    return build_structure(
        parse_report(text, ticker="MLTM", fiscal_year=fy, filing_id=1, settings=settings), settings
    )


def doc(*pages: str) -> str:
    """A synthetic style A report, one string per page."""
    return "".join(f"<!-- page {i} -->\n{body}\n" for i, body in enumerate(pages, 1))


TOC = "# תוכן עניינים\n\n" + "\n".join(
    f"{i}. {t}"
    for i, t in enumerate(
        ["פעילות החברה", "תחומי הפעילות", "שיווק והפצה", "מימון", "שירותי שכר וחיסכון", "דיון בגורמי סיכון"],
        1,
    )
)


@pytest.fixture(scope="module")
def fixture_b():
    logging.disable(logging.WARNING)
    yield structure_of(fixture_text("mltm_2025_style_b.md"))
    logging.disable(logging.NOTSET)


# ---------------------------------------------------------------- 4.4 chapters


def test_fixture_five_chapters_once_outside_toc(fixture_b):
    c = fixture_b.coverage
    assert c.chapters_found == ["business", "directors", "financials", "additional", "governance"]
    assert c.chapters_missing == [] and c.chapters_duplicated == []
    chapters = [n for n in fixture_b.nodes if n.kind == "chapter"]
    assert [n.node_id for n in chapters if n.chapter != "other"] == [
        "business",
        "directors",
        "financials",
        "additional",
        "governance",
    ]
    business = fixture_b.node("business")
    assert business.pages[0] > 3  # the TOC page (3) lists every chapter but is ignored
    assert fixture_b.node("front").pages[0] == 1


def test_chapter_ordinal_tolerates_broken_word():
    assert chapter_ordinal("פרק שלישי דוחות כספיים") == 3
    assert chapter_ordinal("פרק ש לישי דוחות כספיים מאוחדים") == 3  # FY2024 text extraction
    assert chapter_ordinal("פרק רביעי לדוח תקופתי") == 4
    assert chapter_ordinal("פרקים נוספים") is None


def test_missing_and_duplicate_chapters_reported():
    s = structure_of(
        doc(
            "# פרק ראשון\n\n## תיאור עסקי התאגיד",
            "גוף",
            "# פרק שני\n\n## דוח הדירקטוריון",
            "# פרק ראשון\n\n## תיאור עסקי",
        )
    )
    assert s.coverage.chapters_duplicated == ["business"]
    assert set(s.coverage.chapters_missing) == {"financials", "additional", "governance"}
    assert any("found again" in w for w in s.warnings) and any(
        "'financials' not found" in w for w in s.warnings
    )


def test_cross_reference_is_not_a_chapter():
    s = structure_of(doc("# פרק ראשון\n\nתיאור", "לפרטים ר' פרק שני לדוח זה ואת דוח הדירקטוריון הכלול בדוח."))
    assert s.coverage.chapters_found == ["business"]


# ---------------------------------------------------------------- 4.5 TOC-anchored sections


def test_toc_25_body_22_found_by_title(fixture_b):
    entry = next(e for e in fixture_b.toc if e.title == "דיון בגורמי סיכון")
    assert entry.number == "25" and entry.matched_node == "business-22"
    risk = fixture_b.node("business-22")
    assert risk.number == "22" and risk.title == "דיון בגורמי סיכון" and risk.kind == "section"


def test_fewer_than_minimum_sections_warns(fixture_b):
    assert fixture_b.coverage.business_sections < 10
    warning = next(w for w in fixture_b.warnings if w.startswith("only"))
    assert "minimum 10" in warning and "TOC entries 25" in warning


def test_sections_numbers_glued_spelling_and_references():
    s = structure_of(
        doc(
            "# פרק ראשון - תיאור עסקי החברה",
            TOC,
            "1. פעילות החברה\n\nלפרטים ר' סעיף 3 שיווק והפצה להלן.\n\n"
            "בנוסף, מימון הלחימה השפיע על המשק.\n\n**2. תחומי הפעילות**\n\nגוף",
            "3.שיווק והפצה להלן פרטים\n\n4.מימון\n\n5. שרותי שכר וחסכון",
            "גוף 5\n\n.6 דיון בגורמי סיכון",
        )
    )
    secs = [(n.number, n.title) for n in s.nodes if n.kind == "section"]
    assert secs == [
        ("1", "פעילות החברה"),
        ("2", "תחומי הפעילות"),
        ("3", "שיווק והפצה"),
        ("4", "מימון"),
        ("5", "שירותי שכר וחיסכון"),
        ("6", "דיון בגורמי סיכון"),
    ]
    assert s.node("business-4").pages == (4, 4)  # not the earlier "מימון הלחימה" mention on page 3


def test_toc_threshold_from_config():
    text = doc("# פרק ראשון - תיאור עסקי", TOC, "1. פעילות החבר\n\n2. תחומי הפעילות")
    assert structure_of(text).coverage.business_sections == 2
    strict = Settings(repeated_line_min_pages=999, toc_match_threshold=100)
    assert structure_of(text, settings=strict).coverage.business_sections == 1


def test_toc_table_rows_parsed():
    table = "### תוכן עניינים\n\n|5|**תיאור ההתפתחות**|**.א**|\n|---|---|---|\n|5|**פעילות החברה**|**1.**|\n|8|**תחומי הפעילות**<br>**של הקבוצה**|**2**<br>**.**<br>|\n|9|**חלוקת דיבידנדים**|**3**<br>**.**|"
    s = structure_of(
        doc("# פרק ראשון", table, "1. פעילות החברה\n\n2. תחומי הפעילות של הקבוצה\n\n3. חלוקת דיבידנדים")
    )
    assert [(e.number, e.title) for e in s.toc] == [
        ("1", "פעילות החברה"),
        ("2", "תחומי הפעילות של הקבוצה"),
        ("3", "חלוקת דיבידנדים"),
    ]
    assert s.coverage.business_sections == 3


# ---------------------------------------------------------------- 4.6 subsections, directors, financials


SUB_FORMS = {
    "dotted": ("22.1.1. מצב בטחוני וכלכלי", "22.1.1", "מצב בטחוני וכלכלי"),
    "leading_dot": (".22.1.2 שינויים בשערי החליפין", "22.1.2", "שינויים בשערי החליפין"),
    "heading": ("## 22.1.3 תלות בתקציבי המדינה", "22.1.3", "תלות בתקציבי המדינה"),
    "title_first": ("**כניסה לתחומי פעילות חדשים .22.1.4**", "22.1.4", "כניסה לתחומי פעילות חדשים"),
    "orphan": (".22.1.5\nהערכת הסיכונים", "22.1.5", "הערכת הסיכונים"),
    "glued": (
        '22.1.6. מכסים: הקבוצה רוכשת חלק מהמוצרים המשווקים ללקוחותיה מספקים בחו"ל ולכן גידול במכסים עלול לפגוע ברווחיה ובתוצאותיה העסקיות לאורך זמן רב.',
        "22.1.6",
        "מכסים",
    ),
}


@pytest.mark.parametrize("form", list(SUB_FORMS))
def test_each_numbering_form(form):
    line, number, title = SUB_FORMS[form]
    text = doc(
        "# פרק ראשון - תיאור עסקי",
        "# תוכן עניינים\n\n22. דיון בגורמי סיכון\n23. אחר\n24. עוד",
        f"22. דיון בגורמי סיכון\n\n22.1. גורמים חיצוניים\n\n{line}\n\nגוף הסעיף. כמפורט בסעיף 22.1.9 לעיל.",
    )
    node = structure_of(text).node(f"business-{number}")
    assert node is not None, f"{form}: {number} not found"
    assert (node.number, node.title, node.kind, node.parent) == (number, title, "subsection", "business-22.1")
    assert structure_of(text).node("business-22.1.9") is None  # a cross-reference, not a heading


def test_orphan_number_followed_by_heading_has_no_title():
    text = doc(
        "# פרק ראשון",
        "# תוכן עניינים\n\n22. סיכונים\n23. א\n24. ב",
        "22. סיכונים\n\n.22.2.3\n\n22.2.4. תמחור פרויקטים",
    )
    s = structure_of(text)
    assert s.node("business-22.2.3").title == "22.2.3"
    assert s.node("business-22.2.4").title == "תמחור פרויקטים"


def test_directors_lettered_headings(fixture_b):
    part = fixture_b.node("directors-part-1")
    assert part.title == "הסברי הדירקטוריון למצב עסקי התאגיד" and part.parent == "directors"
    lettered = [fixture_b.node(c) for c in part.children]
    assert [(n.number, n.title) for n in lettered][:2] == [
        ("א", "הקבוצה וסביבתה העסקית"),
        ("ב", "הסביבה העסקית"),
    ]


def test_directors_letters_must_progress():
    text = doc(
        "# פרק שני\n\n## דוח הדירקטוריון",
        "## א. כללי\n\nגוף",
        "## ב. תוצאות\n\nא. פריט ברשימה\n\n## ג. נזילות",
    )
    s = structure_of(text)
    assert [(n.number, n.title) for n in s.nodes if n.chapter == "directors" and n.kind != "chapter"] == [
        ("א", "כללי"),
        ("ב", "תוצאות"),
        ("ג", "נזילות"),
    ]


def test_financial_statements_parts(fixture_b):
    fin = fixture_b.node("financials")
    kinds = [fixture_b.node(c).kind for c in fin.children]
    assert "auditor_report" in kinds and "statement" in kinds
    auditor = next(fixture_b.node(c) for c in fin.children if fixture_b.node(c).kind == "auditor_report")
    assert "רואה" in auditor.title or "ראי" in auditor.title
    note = fixture_b.node("financials-note-1")
    assert (note.title, note.kind, note.parent) == ("כללי", "note", "financials-notes")


def test_auditor_heading_must_start_the_line():
    text = doc(
        "# פרק שלישי\n\n## דוחות כספיים",
        "# דוח רואה החשבון המבקר לבעלי המניות\n\nחוות דעת",
        "שותף ההתקשרות של הביקורת נשוא דוח רואה החשבון המבקר הוא פלוני.\n\nדוחות מאוחדים על המצב הכספי",
    )
    s = structure_of(text)
    assert [n.title for n in s.nodes if n.kind == "auditor_report"] == ["דוח רואה החשבון המבקר לבעלי המניות"]
    assert [n.title for n in s.nodes if n.kind == "statement"] == ["דוחות מאוחדים על המצב הכספי"]


def test_chapter_title_skips_brand_lines():
    s = structure_of(
        doc('# פרק חמישי\n## שאלון ממשל תאגידי\n\nMalamTeam\n\nwww.malamteam.com | מלם-תים בע"מ 0 |', "גוף")
    )
    assert s.node("chapter-5").title == "פרק חמישי שאלון ממשל תאגידי"


def test_notes_in_every_layout():
    text = doc(
        "# פרק שלישי\n\n## דוחות כספיים",
        "ביאור 1 - כללי\n\nגוף",
        "ביאור 1 - כללי (המשך)\n\nעיקרי המדיניות החשבונאיות - 2 ביאור\n\nגוף",
        "- **ביאור 3 - מזומנים**\n\n- 4 ביאור: שיקולי דעת\n\n**<u>ביאור 5 - לקוחות</u>**",
        "ראה ביאור 9 לעיל.\n\n## ביאור 7 - מלאי",
    )
    s = structure_of(text)
    notes = [(n.number, n.title) for n in s.nodes if n.kind == "note"]
    assert notes == [
        ("1", "כללי"),
        ("2", "עיקרי המדיניות החשבונאיות"),
        ("3", "מזומנים"),
        ("4", "שיקולי דעת"),
        ("5", "לקוחות"),
        ("7", "מלאי"),
    ]
    assert s.coverage.note_numbers_missing == [6]


def test_tree_ranges_are_nested(fixture_b):
    for n in fixture_b.nodes:
        assert n.para_range[0] <= n.para_range[1] and n.pages[0] <= n.pages[1]
        if n.parent:
            p = fixture_b.node(n.parent)
            assert p.para_range[0] <= n.para_range[0] and n.para_range[1] <= p.para_range[1]
            assert n.node_id in p.children
    assert len({n.node_id for n in fixture_b.nodes}) == len(fixture_b.nodes)


def test_stable_structure_across_runs():
    text = fixture_text("mltm_2025_style_b.md")
    assert structure_of(text).model_dump() == structure_of(text).model_dump()


# ---------------------------------------------------------------- full reports (when cached)


@pytest.mark.live_data
@pytest.mark.parametrize("fy", [2024, 2025])
def test_live_chapters_once_and_sections(fy):
    s = build_structure(
        parse_report(live_report(fy), ticker="MLTM", fiscal_year=fy, filing_id=LIVE_FILINGS[fy])
    )
    c = s.coverage
    assert c.chapters_found == ["business", "directors", "financials", "additional", "governance"]
    assert c.chapters_duplicated == [] and c.chapters_missing == []
    assert c.business_sections >= 22 and c.business_sections_matched_from_toc == c.business_toc_entries
    risk = s.node("business-22")
    assert risk.title == "דיון בגורמי סיכון"
    assert [s.node(x).number for x in risk.children] == ["22.1", "22.2", "22.3"]


@pytest.mark.live_data
def test_live_fy2025_risk_and_notes():
    s = build_structure(
        parse_report(live_report(2025), ticker="MLTM", fiscal_year=2025, filing_id=LIVE_FILINGS[2025])
    )
    assert next(e for e in s.toc if e.matched_node == "business-22").number == "25"
    ai = s.node("business-22.2.3")
    assert ai.title.startswith("סיכונים הנובעים משימוש ופיתוח טכנולוגיות בינה מלאכותית")
    assert s.node("financials-note-32").title.startswith("דיווח מגזרי")
    assert s.coverage.notes >= 24 and s.coverage.auditor_reports >= 2 and s.coverage.statements >= 5
