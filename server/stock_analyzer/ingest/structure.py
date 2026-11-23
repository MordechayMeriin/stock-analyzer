"""Paragraphs → structure tree (plan.md §1.5, report-parsing spec).

1. **Chapters** by Hebrew markers (``פרק ראשון`` … / title markers), ignoring table-of-contents
   pages; each chapter is expected once.
2. **Business sections anchored on the report's own TOC.** The TOC is parsed into ordered
   (number, title) pairs; each title is found in the body, in order, by fuzzy match
   (``token_set_ratio ≥ toc_match_threshold``). TOC numbers are display-only: the body's own
   number (which often differs, e.g. TOC 25 vs body 22 for risk factors) is shown.
3. **Subsections** by tolerant numbering patterns: ``22.1.1. title``, ``.22.1.1 title``,
   ``## 22.1.2 title``, ``title .22.3.6``, a number alone on its line, and a title glued to
   its body text.
4. **Directors' report** by lettered headings (and ``חלק א'`` parts); **financial statements**
   into the auditor's report(s), the primary statements and the ``ביאור N`` notes.
5. **Sanity**: each chapter once, ≥ ``min_business_sections`` business sections; coverage logged.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel
from rapidfuzz import fuzz

from stock_analyzer.config import Settings
from stock_analyzer.ingest.normalize import match_key, normalize, normalize_title
from stock_analyzer.ingest.parse_md import PageInfo, Paragraph, ParsedReport
from stock_analyzer.ingest.vocab import (
    CHAPTER_TITLES_HE,
    CHAPTER_WORDS,
    GERESH,
    MAIN_CHAPTERS,
    ORDINAL_LETTERS,
    ORDINAL_WORDS,
    ORDINAL_WORDS_LONGEST_FIRST,
    TOC_HEADINGS,
    Chapter,
    chapter_title_prefix,
    classify_chapter_title,
)

log = logging.getLogger(__name__)

STRUCTURE_VERSION = "2"

NodeKind = Literal["chapter", "section", "subsection", "note", "auditor_report", "statement", "other"]


class Node(BaseModel):
    node_id: str
    kind: NodeKind
    chapter: Chapter
    number: str | None  # display only, never used for matching
    title: str
    title_norm: str
    level: int
    para_range: tuple[int, int]  # inclusive paragraph seq range
    pages: tuple[int, int]  # inclusive page_index range
    children: list[str] = []
    parent: str | None = None


class TocEntry(BaseModel):
    number: str | None
    title: str
    matched_node: str | None = None


class Coverage(BaseModel):
    paragraphs: int
    paragraphs_in_chapters: int
    chapters_found: list[str]
    chapters_missing: list[str]
    chapters_duplicated: list[str]
    business_toc_entries: int
    business_sections: int
    business_sections_matched_from_toc: int
    subsections: int
    directors_headings: int
    notes: int
    note_numbers_missing: list[int]
    auditor_reports: int
    statements: int


class Structure(BaseModel):
    ticker: str
    fiscal_year: int
    filing_id: int
    structure_version: str = STRUCTURE_VERSION
    nodes: list[Node]  # pre-order
    roots: list[str]
    toc: list[TocEntry]
    coverage: Coverage
    warnings: list[str]

    def node(self, node_id: str) -> Node | None:
        return next((n for n in self.nodes if n.node_id == node_id), None)


# ---------------------------------------------------------------- patterns

_CHAPTER_ORDINAL = re.compile(rf"^פרק\s+({'|'.join(ORDINAL_WORDS_LONGEST_FIRST)})(?![א-ת])")


def chapter_ordinal(text: str) -> int | None:
    """The chapter ordinal of a heading like "פרק שלישי", tolerating a stray space inside
    the word ("פרק ש לישי"), which the provider's text extraction sometimes produces."""
    if m := _CHAPTER_ORDINAL.match(text):
        return ORDINAL_WORDS[m.group(1)]
    compact = re.sub(r"\s+", "", text[:24])
    if not compact.startswith("פרק"):
        return None
    rest = compact[3:]
    for word in ORDINAL_WORDS_LONGEST_FIRST:
        if rest.startswith(word):
            return ORDINAL_WORDS[word]
    return None


_REF_BEFORE = re.compile(r"(?:סעיפים|סעיף|ס'|תקנה|תקנות|ביאור|ביאורים|ר'|ראה|ראו|בפרק|פרק)\s*[-–]?\s*$")
_REF_AFTER = re.compile(r"^\s*(?:לעיל|להלן|לדוח|לחוק|לתקנות)")
_SINGLE_BEFORE = re.compile(r"(?:^|[\s(\[*])\.?(\d{1,2})\.?\s*[-–]?\s*$")
_SINGLE_AFTER = re.compile(r"^\s*\.(\d{1,2})\.?(?:\s|$)")
_LETTER_BEFORE = re.compile(r"(?:^|[\s*])\.?([א-ת])['׳]?\.\s*$")
_MULTI = re.compile(r"(?<![\d.,])\.?(\d{1,2}(?:\.\d{1,3}){1,4})\.?(?![\d,])")
_LETTERED = re.compile(r"^\.?([א-ת])['׳]?\s*[.)]\s*(\S.*)$")
_PART = re.compile(r"^חלק\s+([א-ת])['׳]?\s*[-–:.]?\s*(.*)$")
_NOTE_PATTERNS = (
    re.compile(r"^ביאור\s+(\d{1,2})\s*(?:[-–:]\s*(.*))?$"),
    re.compile(r"^(\d{1,2})\s+ביאור\s*(?:[-–:]\s*(.*))?$"),
    re.compile(r"^(.*?)\s*[-–]\s*(\d{1,2})\s+ביאור$"),
)
_AUDITOR = re.compile(r"^דוח(?:ות)?\s+(?:מיוחד\s+של\s+)?(?:רואה|רואי|ראי|רוא\"ח)\s+ה?חשבון")
_STATEMENT = re.compile(
    r"^(?:דוחות|דוח|נתונים)\s+(?:מאוחדים\s+|מאוחד\s+|כספיים\s+)?על\s+(?:ה)?(?:מצב\s+הכספי|רווח\s+(?:ו|או\s+)הפסד|רווח\s+הכולל|"
    r"הרווח\s+הכולל|רווח\s+כולל|שינויים\s+בהון|השינויים\s+בהון|תזרימי\s+המזומנים|תזרימי\s+מזומנים)"
)
_SEPARATE = re.compile(r"^מידע\s+כספי\s+נפרד")
_CONTINUED = re.compile(r"\s*\(המשך\)\s*")
_SENTENCE_END = re.compile(r"(?<!\d)[.:](?!\d)")
_HEB_LETTERS = "אבגדהוזחטיכלמנסעפצקרשת"


def _first_line(p: Paragraph) -> str:
    return normalize_title(p.raw.split("\n", 1)[0])


def _is_heading_like(p: Paragraph, max_len: int = 150) -> bool:
    if p.in_table:
        return False
    first = p.raw.split("\n", 1)[0].strip()
    if p.heading_level:
        return True
    text = normalize_title(first)
    if not text or len(text) > max_len:
        return False
    return first.startswith("**") or len(text) <= 80


def _letter_index(letter: str) -> int:
    return _HEB_LETTERS.index(letter) + 1 if letter in _HEB_LETTERS else 0


@dataclass
class _Start:
    """A node start found in the paragraph stream (ranges are filled in later)."""

    node_id: str
    kind: NodeKind
    chapter: Chapter
    number: str | None
    title: str
    level: int
    seq: int
    pos: int = 0  # character position inside the paragraph (orders several starts in one paragraph)


# ---------------------------------------------------------------- TOC


def _toc_pages(paragraphs: list[Paragraph]) -> set[int]:
    pages: set[int] = set()
    for p in paragraphs:
        if p.in_table:
            continue
        t = normalize_title(p.text)
        if any(t.startswith(h) for h in TOC_HEADINGS) and len(t) < 40:
            pages.add(p.page_index)
    return pages


def _parse_toc_line(line: str) -> TocEntry | None:
    t = normalize_title(line)
    if not t:
        return None
    m = re.match(r"^\.?(\d{1,2})\s*\.?\s*(?=\D)(.+?)(?:\s+\d{1,3}(?:-\d{1,3})?)?$", t)
    if m and re.search(r"[א-ת]", m.group(2)):
        return TocEntry(number=m.group(1), title=m.group(2).strip(" .-–"))
    m = re.match(r"^(.+?[א-ת].*?)\s+\.?(\d{1,2})\.?$", t)
    if m and not re.match(r"^[א-ת]['׳]?\.", t):
        return TocEntry(number=m.group(2), title=m.group(1).strip(" .-–"))
    return None


def _parse_toc_row(row: str) -> TocEntry | None:
    cells = [normalize(c) for c in row.strip().strip("|").split("|")]
    if not cells or all(set(c) <= set("-: ") for c in cells):
        return None
    texts = [c for c in cells if len(re.findall(r"[א-ת]", c)) >= 3]
    if not texts:
        return None
    nums = [re.sub(r"[\s.]", "", c) for c in cells]
    numeric = [n for n in nums if re.fullmatch(r"\d{1,3}", n)]
    lettered = [c for c in cells if re.fullmatch(r"\.?\s*[א-ת]['׳]?\s*\.?", c)]
    if lettered and not numeric[1:]:
        return None  # a lettered part row (".א"), not a numbered section
    if not numeric:
        return None
    number = numeric[-1] if len(numeric) > 1 else numeric[0]
    return TocEntry(number=number, title=max(texts, key=len).strip(" .-–"))


def parse_business_toc(
    paragraphs: list[Paragraph], toc_pages: set[int], business_start_seq: int | None
) -> list[TocEntry]:
    """The business chapter's TOC: the TOC page whose entries precede/open the business chapter."""
    entries: list[TocEntry] = []
    for page in sorted(toc_pages):
        page_paras = [p for p in paragraphs if p.page_index == page]
        page_entries: list[TocEntry] = []
        stop = False
        for p in page_paras:
            if p.in_table:
                rows = [ln for ln in p.raw.split("\n") if ln.strip().startswith("|")]
                page_entries += [e for e in (_parse_toc_row(r) for r in rows) if e]
                continue
            for line in p.raw.split("\n"):
                t = normalize_title(line)
                if (chapter_ordinal(t) or 0) > 1 and page_entries:
                    stop = True  # the next chapter's TOC begins
                    break
                if e := _parse_toc_line(line):
                    page_entries.append(e)
            if stop:
                break
        if len(page_entries) >= 3:
            entries = page_entries
            if business_start_seq is None or page_paras[0].seq <= business_start_seq + 50:
                break
    return entries


# ---------------------------------------------------------------- chapters


_WORDS = "|".join(CHAPTER_WORDS)
_LETTERS = "".join(ORDINAL_LETTERS)
_ORD_WORD = "|".join(ORDINAL_WORDS_LONGEST_FIRST)
# "פרק א' - title", "פרק ב | title", "פרק שני", "פרק 1: title", "פרק" alone
_OPENER = re.compile(
    rf"^(?P<word>{_WORDS})(?![א-ת])\s*"
    rf"(?:(?P<wordord>{_ORD_WORD})(?![א-ת])|(?P<letter>[{_LETTERS}])[{GERESH}]?(?![א-ת])|(?P<digit>\d{{1,2}})(?!\d))?"
    r"\s*['׳]?\s*[-–|:.]?\s*(?P<title>.*)$"
)
# bidi-reversed: "ב' פרק דוח הדירקטוריון…", "ג ' פרק" (geresh required)
_OPENER_REVERSED = re.compile(
    rf"^(?P<letter>[{_LETTERS}])\s*['׳]\s*(?P<word>{_WORDS})(?![א-ת])\s*(?P<title>.*)$"
)
_TITLE_LINE_MAX = 60


@dataclass
class _Opener:
    word: str
    ordinal: int | None
    digit: bool
    title: str  # the opener line's own title (may be empty)
    continuation: str  # the following short head lines, joined

    def candidates(self) -> list[str]:
        """Titles to classify: the line's own title, then with the following lines appended
        ("פרק רביעי לדוח תקופתי" / "פרטים נוספים על החברה")."""
        return [t for t in (self.title, f"{self.title} {self.continuation}".strip()) if t]


def parse_opener(line: str, following: list[str]) -> _Opener | None:
    """A chapter opener in a page-head line, with its title taken from the same line or, when the
    line holds only the opener, from up to three following short head lines."""
    t = line.strip(" .:-–|")
    m = _OPENER.match(t) or _OPENER_REVERSED.match(t)
    ordinal: int | None = None
    digit = False
    if m is not None and not (
        m.groupdict().get("wordord") or m.group("letter") or m.groupdict().get("digit")
    ):
        if chapter_ordinal(t) is not None:
            m = None  # "פרק ש לישי ..." (a stray space inside the ordinal word)
    if m is None:
        if (n := chapter_ordinal(t)) is None:
            return None
        word, ordinal = "פרק", n
        ordinal_word = next(w for w in ORDINAL_WORDS if ORDINAL_WORDS[w] == n)
        # skip past "פרק" + the ordinal's letters, ignoring the stray spaces between them
        consumed, i = 0, 0
        while i < len(t) and consumed < 3 + len(ordinal_word):
            consumed += not t[i].isspace()
            i += 1
        title = t[i:].strip(" -–|:.")
    else:
        groups = m.groupdict()
        word, title = m.group("word"), m.group("title").strip(" -–|:.")
        if groups.get("wordord"):
            ordinal = ORDINAL_WORDS[groups["wordord"]]
        elif groups.get("letter"):
            ordinal = ORDINAL_LETTERS[groups["letter"]]
        elif groups.get("digit"):
            ordinal, digit = int(groups["digit"]), True
        if ordinal is None and title:
            return None  # "חלק מחברות הביטוח", "פרק המונופולין": prose, not an opener
    parts: list[str] = []
    for nxt in following[:3]:
        if len(nxt) > _TITLE_LINE_MAX or _OPENER.match(nxt) or _OPENER_REVERSED.match(nxt):
            break
        if re.search(r"\||www\.|https?:", nxt):
            continue  # brand and footer-like lines ("www.x.com | חברה | 3")
        parts.append(nxt)
    return _Opener(word=word, ordinal=ordinal, digit=digit, title=title, continuation=" ".join(parts))


def _first_seq_of_pages(paragraphs: list[Paragraph]) -> dict[int, int]:
    first: dict[int, int] = {}
    for p in paragraphs:
        first.setdefault(p.page_index, p.seq)
    return first


def find_chapters(
    report: ParsedReport, toc_pages: set[int], settings: Settings, warnings: list[str]
) -> tuple[list[_Start], list[str]]:
    """Chapters from openers in page heads (design D2/D3). A chapter starts at the first paragraph
    of its opener's page. Rules, in order: a digit ordinal is an inner part; once a classified
    opener has fixed the report's chapter word (פרק or חלק), openers with the other word are inner
    parts; a classified title starts that chapter (a repeat right after itself is a cover/first
    page; after another chapter it is a duplicate); an unclassified title starts an "other" chapter
    only with an ordinal above the last one; a page's first head line that starts with a chapter
    title can start a chapter not found yet."""
    threshold = settings.chapter_match_threshold
    first_seq = _first_seq_of_pages(report.paragraphs)
    seqs = sorted(first_seq.items())

    def page_start(page: int) -> int | None:
        return next((seq for idx, seq in seqs if idx >= page), None)

    starts: list[_Start] = []
    found: dict[str, int] = {}
    duplicated: list[str] = []
    chapter_word: str | None = None
    last_key: str | None = None
    last_ordinal = 0

    def start(kind: Chapter, page: PageInfo, ordinal: int | None, title: str) -> None:
        nonlocal last_key, last_ordinal
        seq = page_start(page.index)
        if seq is None:
            return
        key = kind if kind != "other" else f"other:{ordinal}"
        found[key] = seq
        last_key = key
        if ordinal:
            last_ordinal = max(last_ordinal, ordinal)
        node_title = CHAPTER_TITLES_HE[kind] if kind != "other" else normalize_title(title)[:80]
        node_id = kind if kind != "other" else f"chapter-{ordinal}"
        starts.append(_Start(node_id, "chapter", kind, str(ordinal) if ordinal else None, node_title, 1, seq))

    pages = [p for p in report.pages if p.index not in toc_pages and p.head]

    def openers(page: PageInfo) -> list[tuple[str, _Opener]]:
        return [
            (line, op) for i, line in enumerate(page.head) if (op := parse_opener(line, page.head[i + 1 :]))
        ]

    def classify(op: _Opener) -> Chapter | None:
        return next((k for k in (classify_chapter_title(t, threshold) for t in op.candidates()) if k), None)

    # First pass: the ordinals the main chapters use. An opener whose title names no chapter
    # becomes an "other" chapter only on a free ordinal: Rami Levy numbers its business parts
    # "חלק ב'", "חלק ד'" with the same word as its chapters, Malam has unnamed chapters 5 and 7.
    main_ordinals: set[int] = set()
    for page in pages:
        for _, op in openers(page):
            if not op.digit and op.ordinal and classify(op) is not None:
                chapter_word = chapter_word or op.word
                if op.word == chapter_word:
                    main_ordinals.add(op.ordinal)
    chapter_word = None

    for page in pages:
        started = False
        for line, op in openers(page):
            if op.digit:
                continue
            if chapter_word is not None and op.word != chapter_word:
                continue
            titles = op.candidates()
            kind = classify(op)
            if kind is not None:
                chapter_word = chapter_word or op.word
                if kind in found:
                    if last_key != kind:
                        duplicated.append(kind)
                        warnings.append(f"chapter {kind!r} found again on page {page.index}")
                    continue
                start(kind, page, op.ordinal, titles[0])
                started = True
                break
            if (
                chapter_word is not None
                and op.ordinal
                and op.ordinal > last_ordinal
                and op.ordinal not in main_ordinals
            ):
                start("other", page, op.ordinal, f"{line} {op.continuation}" if not op.title else line)
                started = True
                break
        if started:
            continue
        kind = chapter_title_prefix(page.head[0], threshold)
        if kind is not None and kind not in found:
            start(kind, page, None, page.head[0])

    # Fallback for main chapters still missing: the first page, in the chapter's canonical place,
    # whose page-edge chapter header names it (a running header, or a header at the page's foot
    # such as "פרק ו | דוח שנתי בדבר אפקטיביות הבקרה הפנימית" when the cover is garbled).
    for idx, kind in enumerate(MAIN_CHAPTERS):
        if kind in found:
            continue
        lo = max((found[k] for k in MAIN_CHAPTERS[:idx] if k in found), default=-1)
        hi = min((found[k] for k in MAIN_CHAPTERS[idx + 1 :] if k in found), default=10**9)
        for page in pages:
            seq = page_start(page.index)
            if seq is None or not lo < seq < hi:
                continue
            edge = ([page.running_header] if page.running_header else []) + page.foot
            if any(_edge_kind(line, chapter_word, threshold) == kind for line in edge):
                start(kind, page, None, CHAPTER_TITLES_HE[kind])
                warnings.append(f"chapter {kind!r} located from a page-edge header on page {page.index}")
                break
    starts.sort(key=lambda s: s.seq)
    return starts, duplicated


def _edge_kind(line: str, chapter_word: str | None, threshold: int) -> Chapter | None:
    """The chapter a page-edge header names: "פרק ו | <title>" or a bare chapter title."""
    op = parse_opener(line, [])
    if op is not None:
        if op.digit or (chapter_word is not None and op.word != chapter_word) or not op.title:
            return None
        return classify_chapter_title(op.title, threshold)
    return chapter_title_prefix(line, threshold)


# ---------------------------------------------------------------- business sections


_EDGE_PREFIX = re.compile(r"^(?:\.?\d{1,2}(?:\.\d{1,3})*\.?|[א-ת]['׳]?\.)\s*")
_EDGE_SUFFIX = re.compile(r"\s*\.?\d{1,2}(?:\.\d{1,3})*\.?$")


def _match_title_in(text: str, title: str, threshold: int) -> tuple[int, int, int] | None:
    """(score, start, end) of the best fuzzy occurrence of ``title`` inside ``text``.
    Both strings are expected to be :func:`match_key` keys."""
    if len(title) < 2:
        return None
    align = fuzz.partial_ratio_alignment(title, text, score_cutoff=max(threshold - 10, 0))
    if align is None:
        return None
    start, end = align.dest_start, align.dest_end
    # extend to word boundaries for the order-insensitive confirmation
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    while end < len(text) and not text[end].isspace():
        end += 1
    # a number glued to the title ("12.שיווק", "title .22") belongs outside the window
    if m := _EDGE_PREFIX.match(text[start:end]):
        if m.end() < end - start:
            start += m.end()
    if m := _EDGE_SUFFIX.search(text[start:end]):
        if m.start() > 0:
            end = start + m.start()
    score = fuzz.token_set_ratio(title, text[start:end])
    return (int(score), start, end) if score >= threshold else None


def find_business_sections(
    paragraphs: list[Paragraph],
    toc: list[TocEntry],
    first_seq: int,
    last_seq: int,
    toc_pages: set[int],
    settings: Settings,
) -> list[_Start]:
    body = [
        p
        for p in paragraphs
        if first_seq <= p.seq <= last_seq and p.page_index not in toc_pages and not p.in_table
    ]
    texts = {p.seq: match_key(normalize(p.raw)) for p in body}
    starts: list[_Start] = []
    cursor = (first_seq, 0)
    last_number = 0
    used_ids: set[str] = set()
    for idx, entry in enumerate(toc):
        found: tuple[Paragraph, int, str | None, str] | None = None
        for p in body:
            if (p.seq, 10**9) < (cursor[0], cursor[1]) or p.seq < cursor[0]:
                continue
            text = texts[p.seq]
            offset = cursor[1] if p.seq == cursor[0] else 0
            search = text[offset:]
            key = match_key(entry.title)
            hit = _match_title_in(search, key, settings.toc_match_threshold)
            while hit:
                score, s, e = hit
                before, after = search[max(0, s - 12) : s], search[e : e + 10]
                number: str | None = None
                kind = "none"
                if (m := _SINGLE_BEFORE.search(before)) and not _REF_BEFORE.search(
                    search[: s - len(m.group(0))]
                ):
                    number, kind = m.group(1), "num"
                elif (m := _SINGLE_AFTER.match(after)) and not _REF_AFTER.match(after[m.end() :]):
                    number, kind = m.group(1), "num"
                elif m := _LETTER_BEFORE.search(before):
                    number, kind = m.group(1), "letter"
                ok = False
                if kind == "num" and int(number) > last_number:
                    ok = True
                elif kind == "letter":
                    ok = True
                elif kind == "none" and s <= 3 and _is_heading_like(p) and score >= 95:
                    ok = True
                if ok:
                    found = (p, offset + s, number if kind != "none" else None, kind)
                    break
                nxt = search[e:]
                sub = _match_title_in(nxt, key, settings.toc_match_threshold)
                hit = (sub[0], sub[1] + e, sub[2] + e) if sub else None
            if found:
                break
        if not found:
            continue
        p, pos, number, kind = found
        if kind == "num":
            last_number = int(number)
        display = number
        if kind == "num":
            node_id = f"business-{number}"
        elif kind == "letter":
            node_id = f"business-part-{_letter_index(number)}"
        else:
            node_id = f"business-t{idx + 1}"
        if kind == "none":
            # the body heading lost its number: infer it from the first subsection ("10.1 ...")
            for q in [x for x in body if x.seq >= p.seq][:4]:
                m = _MULTI.search(normalize_title(q.raw.split("\n", 1)[0]))
                if m and int(m.group(1).split(".")[0]) == last_number + 1:
                    display = m.group(1).split(".")[0]
                    last_number = int(display)
                    node_id = f"business-{display}"
                    break
        while node_id in used_ids:
            node_id += "b"
        used_ids.add(node_id)
        entry.matched_node = node_id
        starts.append(_Start(node_id, "section", "business", display, entry.title, 2, p.seq, pos))
        cursor = (p.seq, pos + 1)
    return starts


def find_subsections(
    paragraphs: list[Paragraph], section: _Start, end_seq: int, settings: Settings
) -> list[_Start]:
    if not section.number or not section.number.isdigit():
        return []
    root = section.number
    starts: list[_Start] = []
    last: tuple[int, ...] = (int(root),)
    seen: set[str] = set()
    body = [p for p in paragraphs if section.seq <= p.seq <= end_seq and not p.in_table]
    for bi, p in enumerate(body):
        lines = [normalize_title(ln) for ln in p.raw.split("\n")]
        base = 0
        for li, line in enumerate(lines):
            if not line:
                continue
            for m in _MULTI.finditer(line):
                num = m.group(1)
                parts = num.split(".")
                if parts[0] != root or num in seen:
                    continue
                tup = tuple(int(x) for x in parts)
                if tup <= last:
                    continue
                before, after = line[: m.start()], line[m.end() :]
                if _REF_BEFORE.search(before) or _REF_AFTER.match(after):
                    continue
                if before.strip() and not after.strip():
                    title = before.strip(" .:-–*")  # "title .22.3.6"
                    if p.seq == section.seq and m.start() < 0:
                        continue
                elif not after.strip():
                    # a number alone on its line: the title is the next non-empty line
                    nxt = next((x for x in lines[li + 1 :] if x), None)
                    if nxt is None and bi + 1 < len(body):
                        nxt = _first_line(body[bi + 1])
                    title = (nxt or "")[:120]
                    if _MULTI.match(title):
                        title = ""  # the next line is another numbered heading: this title was lost
                else:
                    if (
                        before.strip()
                        and not re.search(r"[.:;)\]]\s*$|^[א-ת]['׳]?\.\s.*$", before.strip())
                        and m.start() > 0
                    ):
                        # mid-line numbers must follow a sentence end or a heading (2024 style)
                        if not re.search(r"[א-ת\w\"']\s*$", before):
                            continue
                    rest = after.strip(" .:-–")
                    nxt_num = _MULTI.search(rest)
                    if nxt_num and nxt_num.group(1).split(".")[0] == root:
                        rest = rest[: nxt_num.start()].strip()
                    if (
                        len(rest) <= settings.glued_title_max_chars
                        and (li == 0 or len(line) <= 150)
                        and not _SENTENCE_END.search(rest[:-1] or "x")
                    ):
                        title = rest
                    else:
                        cut = _SENTENCE_END.search(rest[: settings.glued_title_max_chars])
                        if cut:
                            title = rest[: cut.start()]
                        else:
                            words, acc = rest.split(), ""
                            for w in words:
                                if len(acc) + len(w) + 1 > 60:
                                    break
                                acc = f"{acc} {w}".strip()
                            title = acc
                seen.add(num)
                last = tup
                starts.append(
                    _Start(
                        f"business-{num}",
                        "subsection",
                        "business",
                        num,
                        title.strip(" .:-–*") or num,
                        2 + len(parts) - 1,
                        p.seq,
                        base + m.start(),
                    )
                )
            base += len(line) + 1
    return starts


# ---------------------------------------------------------------- directors' report


def find_directors_headings(paragraphs: list[Paragraph], first_seq: int, last_seq: int) -> list[_Start]:
    starts: list[_Start] = []
    part: str | None = None
    last_letter = 0
    part_idx = 0
    for p in paragraphs:
        if not (first_seq < p.seq <= last_seq) or not _is_heading_like(p, 120):
            continue
        t = _first_line(p)
        if m := _PART.match(t):
            part_idx += 1
            part = str(_letter_index(m.group(1)) or part_idx)
            last_letter = 0
            title = m.group(2).strip(" -–") or t
            starts.append(
                _Start(
                    f"directors-part-{part}", "section", "directors", f"חלק {m.group(1)}'", title, 2, p.seq
                )
            )
            continue
        if m := _LETTERED.match(t):
            idx = _letter_index(m.group(1))
            if idx == 0 or idx <= last_letter or idx > last_letter + 3:
                continue
            last_letter = idx
            title = m.group(2).strip()
            node_id = f"directors-{part}-{idx}" if part else f"directors-{idx}"
            starts.append(
                _Start(
                    node_id,
                    "subsection" if part else "section",
                    "directors",
                    m.group(1),
                    title,
                    3 if part else 2,
                    p.seq,
                )
            )
    return starts


# ---------------------------------------------------------------- financial statements


def _note_heading(t: str) -> tuple[int, str] | None:
    t = re.sub(r"^[-*•]\s*", "", t).strip()
    if len(t) > 110:
        return None
    for i, pat in enumerate(_NOTE_PATTERNS):
        if m := pat.match(t):
            if i == 2:
                num, title = int(m.group(2)), m.group(1)
            else:
                num, title = int(m.group(1)), m.group(2) or ""
            return num, _CONTINUED.sub(" ", title).strip(" -–:")
    return None


def find_financials_parts(
    paragraphs: list[Paragraph], first_seq: int, last_seq: int, toc_pages: set[int]
) -> tuple[list[_Start], list[int]]:
    starts: list[_Start] = []
    group = "notes"
    group_started = False
    note_numbers: dict[str, set[int]] = {}
    last_note = 0
    auditor_n = statement_n = 0
    last_statement = ""
    separate = False
    for p in paragraphs:
        if not (first_seq < p.seq <= last_seq) or p.in_table or p.page_index in toc_pages:
            continue
        for line in p.raw.split("\n")[:3]:
            t = normalize_title(line)
            if not t:
                continue
            if _SEPARATE.match(t) and not separate and len(t) < 60:
                separate = True
                group, group_started, last_note = "separate", False, 0
                starts.append(_Start("financials-separate", "other", "financials", None, t, 2, p.seq))
                break
            if (note := _note_heading(t)) is not None:
                num, title = note
                if num <= last_note:
                    break  # continuation page "(המשך)" or a repeat
                if not group_started:
                    group_started = True
                    if group == "notes":
                        starts.append(
                            _Start(
                                "financials-notes",
                                "other",
                                "financials",
                                None,
                                "ביאורים לדוחות הכספיים",
                                2,
                                p.seq,
                            )
                        )
                last_note = num
                note_numbers.setdefault(group, set()).add(num)
                prefix = "financials-note" if group == "notes" else "financials-separate-note"
                level = 3
                starts.append(
                    _Start(
                        f"{prefix}-{num}",
                        "note",
                        "financials",
                        str(num),
                        title or f"ביאור {num}",
                        level,
                        p.seq,
                    )
                )
                break
            if group_started:
                continue  # inside the notes: statements/auditor headings no longer start nodes
            if (
                _AUDITOR.search(t)
                and len(t) <= 140
                and (p.heading_level or line.strip().startswith(("#", "**")) or len(t) < 90)
            ):
                key = normalize_title(t)[:60]
                if starts and starts[-1].kind == "auditor_report" and starts[-1].title[:60] == key:
                    break
                auditor_n += 1
                node_id = (
                    f"financials-auditor-{auditor_n}"
                    if not separate
                    else f"financials-separate-auditor-{auditor_n}"
                )
                starts.append(
                    _Start(node_id, "auditor_report", "financials", None, t, 3 if separate else 2, p.seq)
                )
                break
            if (m := _STATEMENT.match(t)) and len(t) <= 90:
                key = m.group(0)
                if key == last_statement:
                    break  # the statement's header repeated on its continuation page
                last_statement = key
                statement_n += 1
                node_id = (
                    f"financials-statement-{statement_n}"
                    if not separate
                    else f"financials-separate-statement-{statement_n}"
                )
                starts.append(
                    _Start(node_id, "statement", "financials", None, t, 3 if separate else 2, p.seq)
                )
                break
    found = note_numbers.get("notes", set())
    missing = [n for n in range(1, max(found) + 1) if n not in found] if found else []
    return starts, missing


# ---------------------------------------------------------------- assembly


def _assemble(starts: list[_Start], paragraphs: list[Paragraph]) -> tuple[list[Node], list[str]]:
    """Turn ordered starts into nodes with ranges, parents and children."""
    if not paragraphs:
        return [], []
    starts = sorted(starts, key=lambda s: (s.seq, s.level, s.pos))
    last_seq = paragraphs[-1].seq
    page_of = {p.seq: p.page_index for p in paragraphs}
    nodes: list[Node] = []
    stack: list[tuple[_Start, Node]] = []
    roots: list[str] = []
    for i, s in enumerate(starts):
        # end = just before the next start at the same or a higher level
        end = last_seq
        for t in starts[i + 1 :]:
            if t.level <= s.level:
                end = max(t.seq - 1 if t.seq > s.seq else s.seq, s.seq)
                break
        while stack and stack[-1][0].level >= s.level:
            stack.pop()
        parent = stack[-1][1] if stack else None
        if parent is not None:
            end = min(end, parent.para_range[1])
        node = Node(
            node_id=s.node_id,
            kind=s.kind,
            chapter=s.chapter,
            number=s.number,
            title=s.title,
            title_norm=normalize_title(s.title),
            level=s.level,
            para_range=(s.seq, end),
            pages=(page_of.get(s.seq, 0), page_of.get(end, page_of.get(s.seq, 0))),
            parent=parent.node_id if parent else None,
        )
        if parent is not None:
            parent.children.append(node.node_id)
        else:
            roots.append(node.node_id)
        nodes.append(node)
        stack.append((s, node))
    return nodes, roots


def build_structure(report: ParsedReport, settings: Settings | None = None) -> Structure:
    settings = settings or Settings()
    paras = report.paragraphs
    warnings: list[str] = []
    toc_pages = _toc_pages(paras)

    chapter_starts, duplicated = find_chapters(report, toc_pages, settings, warnings)
    found = [s.chapter for s in chapter_starts if s.chapter != "other"]
    missing = [c for c in MAIN_CHAPTERS if c not in found]
    for c in missing:
        warnings.append(f"chapter {c!r} not found")

    starts: list[_Start] = []
    if paras and (not chapter_starts or chapter_starts[0].seq > paras[0].seq):
        starts.append(_Start("front", "other", "other", None, "שער, תוכן עניינים", 1, paras[0].seq))
    starts += chapter_starts

    bounds: dict[str, tuple[int, int]] = {}
    ordered = sorted(chapter_starts, key=lambda s: s.seq)
    for i, s in enumerate(ordered):
        end = ordered[i + 1].seq - 1 if i + 1 < len(ordered) else paras[-1].seq
        bounds[s.node_id] = (s.seq, end)

    toc: list[TocEntry] = []
    sections: list[_Start] = []
    subsections: list[_Start] = []
    if "business" in bounds:
        b0, b1 = bounds["business"]
        toc = parse_business_toc(paras, toc_pages, b0)
        sections = find_business_sections(paras, toc, b0, b1, toc_pages, settings)
        for i, sec in enumerate(sections):
            end = sections[i + 1].seq if i + 1 < len(sections) else b1
            subsections += find_subsections(paras, sec, end, settings)
        numbered = [s for s in sections if s.number and s.number.isdigit()]
        if len(sections) < settings.min_business_sections:
            warnings.append(
                f"only {len(sections)} business sections found (minimum {settings.min_business_sections}); "
                f"TOC entries {len(toc)}, matched {sum(e.matched_node is not None for e in toc)}"
            )
        unmatched = [e.title for e in toc if e.matched_node is None]
        if unmatched:
            warnings.append(f"TOC entries not found in the body: {unmatched}")
        del numbered
    directors: list[_Start] = []
    if "directors" in bounds:
        directors = find_directors_headings(paras, *bounds["directors"])
    fin: list[_Start] = []
    notes_missing: list[int] = []
    if "financials" in bounds:
        fin, notes_missing = find_financials_parts(paras, *bounds["financials"], toc_pages)
        if notes_missing:
            warnings.append(f"note numbers without a heading: {notes_missing}")

    starts += sections + subsections + directors + fin
    nodes, roots = _assemble(starts, paras)

    in_chapters = sum(1 for p in paras if any(b0 <= p.seq <= b1 for b0, b1 in bounds.values()))
    coverage = Coverage(
        paragraphs=len(paras),
        paragraphs_in_chapters=in_chapters,
        chapters_found=found,
        chapters_missing=missing,
        chapters_duplicated=duplicated,
        business_toc_entries=len(toc),
        business_sections=len(sections),
        business_sections_matched_from_toc=sum(e.matched_node is not None for e in toc),
        subsections=len(subsections),
        directors_headings=len(directors),
        notes=sum(1 for s in fin if s.kind == "note"),
        note_numbers_missing=notes_missing,
        auditor_reports=sum(1 for s in fin if s.kind == "auditor_report"),
        statements=sum(1 for s in fin if s.kind == "statement"),
    )
    for w in warnings:
        log.warning("%s FY%s structure: %s", report.ticker, report.fiscal_year, w)
    return Structure(
        ticker=report.ticker,
        fiscal_year=report.fiscal_year,
        filing_id=report.filing_id,
        nodes=nodes,
        roots=roots,
        toc=toc,
        coverage=coverage,
        warnings=warnings,
    )
