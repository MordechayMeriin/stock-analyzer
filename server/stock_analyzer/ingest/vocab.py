"""Hebrew vocabulary for structure matching (generalize-report-parsing design D1).

Every variant seen across issuers lives here, so supporting a new issuer's wording is a one-line
change: chapter ordinals and words, chapter title variants per chapter kind, note words, and the
auditor's-report and primary-statement heading patterns. Titles are compared on
:func:`stock_analyzer.ingest.normalize.match_key` keys, so spelling variants (``דוח``/``דו"ח``,
``שירותי``/``שרותי``) need no entry of their own.
"""

from __future__ import annotations

import re
from functools import cache
from typing import Literal

from rapidfuzz import fuzz

from stock_analyzer.ingest.normalize import match_key

Chapter = Literal["business", "directors", "financials", "additional", "governance", "other"]
MAIN_CHAPTERS: tuple[Chapter, ...] = ("business", "directors", "financials", "additional", "governance")

# ---------------------------------------------------------------- chapter openers

ORDINAL_WORDS: dict[str, int] = {
    "ראשון": 1,
    "שני": 2,
    "שלישי": 3,
    "רביעי": 4,
    "חמישי": 5,
    "שישי": 6,
    "שביעי": 7,
    "שמיני": 8,
    "תשיעי": 9,
    "עשירי": 10,
}
ORDINAL_WORDS_LONGEST_FIRST = sorted(ORDINAL_WORDS, key=len, reverse=True)
# Letter ordinals ("פרק א'"): the geresh may be missing or extracted as "י" ("פרק אי").
ORDINAL_LETTERS: dict[str, int] = {letter: i for i, letter in enumerate("אבגדהוזחט", start=1)}
GERESH = "'׳י"
# The word that opens a chapter; which one a report uses for chapters (the other numbers parts)
# is decided per report.
CHAPTER_WORDS: tuple[str, ...] = ("פרק", "חלק")

# ---------------------------------------------------------------- chapter titles

CHAPTER_TITLES: dict[Chapter, tuple[str, ...]] = {
    "business": ("תיאור עסקי התאגיד", "תיאור עסקי החברה"),
    "directors": (
        "דוח הדירקטוריון",
        "דוח דירקטוריון",
        "דוח הדירקטוריון על מצב ענייני התאגיד",
        "דוח הדירקטוריון על מצב ענייני החברה",
    ),
    # separate financial information belongs to the financial statements (Malam, El Al)
    "financials": ("דוחות כספיים", "דוחות כספיים מאוחדים", "מידע כספי נפרד"),
    "additional": ("פרטים נוספים על התאגיד", "פרטים נוספים על החברה"),
    "governance": (
        "דוח בדבר אפקטיביות הבקרה הפנימית",
        "דוח שנתי בדבר אפקטיביות הבקרה הפנימית",
        "אפקטיביות הבקרה הפנימית",
        "הצהרות מנהלים",
    ),
}

# Display titles of the main chapters.
CHAPTER_TITLES_HE: dict[str, str] = {
    "business": "תיאור עסקי התאגיד",
    "directors": "דוח הדירקטוריון",
    "financials": "דוחות כספיים",
    "additional": "פרטים נוספים על התאגיד",
    "governance": "אפקטיביות הבקרה הפנימית והצהרות מנהלים",
    "other": "אחר",
}


@cache
def _title_keys() -> tuple[tuple[str, Chapter], ...]:
    return tuple((match_key(v), kind) for kind, variants in CHAPTER_TITLES.items() for v in variants)


def _window_score(vkey: str, key: str) -> float:
    """Best ratio between a variant and any run of as many whole words of the title (word-aligned,
    so "של עסקי החברה" does not pass for "תיאור עסקי החברה"). A title with fewer words than the
    variant is compared whole, so a fragment like "דוח" never matches."""
    vwords, words = vkey.split(), key.split()
    n = len(vwords)
    if len(words) <= n:
        return fuzz.ratio(vkey, key)
    return max(fuzz.ratio(vkey, " ".join(words[i : i + n])) for i in range(len(words) - n + 1))


def classify_chapter_title(title: str, threshold: int) -> Chapter | None:
    """The main chapter a title names, or None. The variant may sit anywhere in a longer title
    (a trailing company name) and may carry small extraction errors ("פרסים נוספים על התאגיד")."""
    key = match_key(title)
    best: tuple[float, Chapter] | None = None
    for vkey, kind in _title_keys():
        score = _window_score(vkey, key)
        if score >= threshold and (best is None or score > best[0]):
            best = (score, kind)
    return best[1] if best else None


def chapter_title_prefix(line: str, threshold: int) -> Chapter | None:
    """The main chapter whose title a line starts with ("פרטים נוספים על התאגיד שם חברה: …"),
    or None. The first word must match exactly; a title followed by "." is a sentence fragment."""
    words = match_key(line).split()
    for vkey, kind in sorted(_title_keys(), key=lambda vk: len(vk[0]), reverse=True):
        vwords = vkey.split()
        n = len(vwords)
        if len(words) < n or words[0] != vwords[0]:
            continue
        if fuzz.ratio(vkey, " ".join(words[:n])) < threshold:
            continue
        if " ".join(words[n:]).startswith("."):
            continue
        return kind
    return None


TOC_HEADINGS: tuple[str, ...] = ("תוכן עניינים", "תוכן העניינים", "רשימת פרקים", "תוכן העניין")

# ---------------------------------------------------------------- financial statements

NOTE_WORDS: tuple[str, ...] = ("ביאור", "באור")
_NOTE_WORD = "(?:" + "|".join(NOTE_WORDS) + ")"
_SEP = r"[-–:]"
NOTE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(rf"^{_NOTE_WORD}\s+(\d{{1,2}})\s*(?:{_SEP}\s*(.*))?$"),  # "ביאור 3 - title", "באור 2: title"
    re.compile(rf"^(\d{{1,2}})\s+{_NOTE_WORD}\s*(?:{_SEP}\s*(.*))?$"),  # "3 ביאור - title"
    re.compile(rf"^(.*?)\s*{_SEP}\s*(\d{{1,2}})\s+{_NOTE_WORD}$"),  # bidi-reversed "title - 3 ביאור"
)
_REPORT = r'(?:דוח|דו"ח|דוחות|דו"חות)'
AUDITOR = re.compile(rf"^{_REPORT}\s+(?:מיוחד\s+של\s+)?(?:רואה|רואי|ראי|רוא\"ח)\s+ה?חשבון")
STATEMENT = re.compile(
    rf"^(?:{_REPORT}|נתונים)\s+(?:מאוחדים\s+|מאוחד\s+|כספיים\s+)?על\s+(?:ה)?(?:מצב\s+הכספי|רווח\s+(?:ו|או\s+)הפסד|"
    r"רווח\s+הכולל|הרווח\s+הכולל|רווח\s+כולל|שינויים\s+בהון|השינויים\s+בהון|תזרימי\s+המזומנים|תזרימי\s+מזומנים)"
)
SEPARATE = re.compile(r"^מידע\s+כספי\s+נפרד")
