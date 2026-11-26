"""Business sections aligned across years (report-diff spec, design D6)."""

from __future__ import annotations

from stock_analyzer.config import Settings
from stock_analyzer.diff.align import AlignedSection, Report, compare_business, title_score
from stock_analyzer.ingest.parse_md import parse_report
from stock_analyzer.ingest.structure import build_structure

SETTINGS = Settings(repeated_line_min_pages=999)


def doc(*pages: str) -> str:
    return "".join(f"<!-- page {i} -->\n{body}\n" for i, body in enumerate(pages, 1))


def report(fy: int, sections: list[tuple[str, str, str]]) -> Report:
    """A synthetic report: (number, title, body) per business section, one page each."""
    toc = "# תוכן עניינים\n\n" + "\n".join(f"{n}. {t}" for n, t, _ in sections)
    pages = [f"**{n}. {t}**\n\n{body}" for n, t, body in sections]
    text = doc("# פרק ראשון - תיאור עסקי החברה", toc, *pages)
    parsed = parse_report(text, ticker="MLTM", fiscal_year=fy, filing_id=fy, settings=SETTINGS)
    return Report(fy, parsed, build_structure(parsed, SETTINGS))


def compare(*reports: Report):
    return compare_business(
        "MLTM",
        reports,
        unchanged_threshold=SETTINGS.diff_unchanged_threshold,
        title_threshold=SETTINGS.diff_title_match_threshold,
        content_threshold=SETTINGS.diff_content_match_threshold,
    )


def by_title(comparison, title: str) -> AlignedSection:
    return next(s for s in comparison.sections if s.title == title)


SAME = "החברה מספקת שירותי מחשוב ללקוחות במגזר הציבורי והעסקי. " * 6
RISK = "הקבוצה חשופה לסיכוני מאקרו, לתחרות ולתלות בלקוחות גדולים. " * 6


def test_renumbered_section_is_aligned_by_title():
    a = report(2024, [("1", "פעילות החברה", SAME), ("2", "מימון", SAME), ("25", "דיון בגורמי סיכון", RISK)])
    b = report(2025, [("1", "פעילות החברה", SAME), ("2", "מימון", SAME), ("22", "דיון בגורמי סיכון", RISK)])
    risk = by_title(compare(a, b), "דיון בגורמי סיכון")
    assert risk.node_ids == {"2024": "business-25", "2025": "business-22"}
    assert [(p.status, p.similarity) for p in risk.pairs] == [("unchanged", 1.0)]


def test_spelling_variant_is_aligned():
    a = report(2024, [("1", "פעילות החברה", SAME), ("2", "שירותי שכר וחיסכון", SAME), ("3", "מימון", SAME)])
    b = report(2025, [("1", "פעילות החברה", SAME), ("2", "שרותי שכר וחסכון", SAME), ("3", "מימון", SAME)])
    payroll = by_title(compare(a, b), "שרותי שכר וחסכון")
    assert set(payroll.node_ids) == {"2024", "2025"}


def test_new_dropped_changed_and_unchanged():
    a = report(
        2024,
        [("1", "פעילות החברה", SAME), ("2", "מימון", SAME), ("3", "הסדר תיחום פעילות", RISK)],
    )
    b = report(
        2025,
        [
            ("1", "פעילות החברה", SAME),
            ("2", "מימון", "בשנת הדוח נטלה החברה הלוואה חדשה מבנק לאומי לצורך רכישת חברת בת. " * 6),
            ("3", "בינה מלאכותית", SAME[::-1]),
        ],
    )
    c = compare(a, b)
    assert [(p.status, p.similarity) for p in by_title(c, "פעילות החברה").pairs] == [("unchanged", 1.0)]
    financing = by_title(c, "מימון").pairs[0]
    assert financing.status == "changed" and financing.similarity < SETTINGS.diff_unchanged_threshold
    assert [p.status for p in by_title(c, "בינה מלאכותית").pairs] == ["new"]
    assert [p.status for p in by_title(c, "הסדר תיחום פעילות").pairs] == ["dropped"]
    assert by_title(c, "הסדר תיחום פעילות").node_ids == {"2024": "business-3"}


def test_three_years_give_two_pairs():
    sections = [("1", "פעילות החברה", SAME), ("2", "מימון", SAME), ("3", "ביטוח", RISK)]
    years = [report(fy, sections) for fy in (2023, 2024, 2025)]
    c = compare(*years)
    assert c.years == [2023, 2024, 2025]
    assert [(p.from_year, p.to_year) for p in c.sections[0].pairs] == [(2023, 2024), (2024, 2025)]


def test_comparison_is_deterministic():
    a = report(2024, [("1", "פעילות החברה", SAME), ("2", "מימון", RISK), ("3", "ביטוח", SAME)])
    b = report(2025, [("1", "פעילות החברה", RISK), ("2", "מימון", SAME), ("3", "ביטוח", SAME)])
    assert compare(a, b) == compare(a, b)
    assert compare(b, a) == compare(a, b)  # input order does not matter


def test_title_scores():
    assert title_score("צ בר הזמנות", "צבר הזמנות") == 100  # a stray space inside a word
    assert (
        title_score(
            "פעילות החברה בתחום תוכנה, פרויקטים ופתרונות", "פעילות החברה בתחום תוכנה פרויקטים ופתרונות ו- AI"
        )
        >= 85
    )
    # different body words glued onto both titles
    assert (
        title_score(
            "מגבלות חיצוניות על חלוקת דיבידנדים חברות בנות של החברה",
            "מגבלות חיצוניות על חלוקת דיבידנדים בחודש נובמ",
        )
        == 100
    )
    # sibling segments share a 3-word prefix and must stay apart
    assert title_score("פעילות החברה בתחום תשתיות וענן", "פעילות החברה בתחום הקמה והשקעה בחברות הזנק") < 85


# ---------------------------------------------------------------- real three-year slices (offline)


def fixture_report(fy: int) -> Report:
    from tests.conftest import fixture_text

    parsed = parse_report(
        fixture_text(f"mltm_{fy}_business_slice.md"),
        ticker="MLTM",
        fiscal_year=fy,
        filing_id=fy,
        settings=SETTINGS,
    )
    return Report(fy, parsed, build_structure(parsed, SETTINGS))


def test_malam_three_year_slices():
    c = compare(*(fixture_report(fy) for fy in (2023, 2024, 2025)))
    sections = {s.title: s for s in c.sections if s.level == 2}

    expected = ["שיווק והפצה", "הון חוזר", "מימון", "רכוש קבוע ומתקנים", "מיסוי", "ביטוח", "הליכים משפטיים"]
    for title in expected:
        assert set(sections[title].node_ids) == {"2023", "2024", "2025"}, title
    # FY2023 lost the "13. הון חוזר" heading; the TOC number recovers it
    assert sections["הון חוזר"].node_ids["2023"] == "business-13"

    def statuses(title: str) -> list[str]:
        return [p.status for p in sections[title].pairs]

    assert statuses("שיווק והפצה") == ["unchanged", "unchanged"]
    assert statuses("מיסוי") == ["changed", "unchanged"]
    assert statuses("הליכים משפטיים") == ["changed", "changed"]
    assert all(p.similarity < 0.5 for p in sections["הליכים משפטיים"].pairs)
