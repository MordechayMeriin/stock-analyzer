"""Chapter-title vocabulary (generalize-report-parsing design D1)."""

import pytest

from stock_analyzer.ingest.vocab import CHAPTER_TITLES, chapter_title_prefix, classify_chapter_title

T = 85


@pytest.mark.parametrize(
    ("kind", "variant"), [(kind, v) for kind, variants in CHAPTER_TITLES.items() for v in variants]
)
def test_every_variant_classifies_to_its_kind(kind, variant):
    assert classify_chapter_title(variant, T) == kind


@pytest.mark.parametrize(
    ("title", "kind"),
    [
        ('דו"ח הדירקטוריון', "directors"),
        ('דו"חות כספיים', "financials"),
        ("פרסים נוספים על התאגיד קבוצת", "additional"),  # extraction error for פרטים
        ('דוח תיאור עסקי התאגיד אל על נתיבי אויר לישראל בע"מ', "business"),
        ("דוח בדבר אפקטיביות הבקרה הפנימית על הדיווח הכספי ועל הגילוי", "governance"),
        ("מידע כספי נפרד ליום 31 בדצמבר 2025", "financials"),
    ],
)
def test_title_variants_and_extraction_noise(title, kind):
    assert classify_chapter_title(title, T) == kind


@pytest.mark.parametrize(
    "title",
    [
        "תיאור ההתפתחות הכללית של עסקי החברה",  # an inner part sharing words with the business title
        "מידע אחר",
        "שאלון ממשל תאגידי",
        "דוח",  # a fragment shorter than every variant
        'לדו"ח תקופתי',
    ],
)
def test_unrelated_titles_do_not_classify(title):
    assert classify_chapter_title(title, T) is None


def test_title_prefix():
    assert (
        chapter_title_prefix('פרטים נוספים על התאגיד שם חברה: אל על נתיבי אויר לישראל בע"מ', T)
        == "additional"
    )
    assert chapter_title_prefix("פרטים נוספים על התאגיד .", T) is None  # end of a sentence (El Al p36)
    assert chapter_title_prefix("דוח הדירקטוריון וההנהלה", T) == "directors"  # prefix only; callers gate it
    assert chapter_title_prefix("לפרטים נוספים על התאגיד", T) is None
