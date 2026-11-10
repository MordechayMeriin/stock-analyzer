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
from stock_analyzer.ingest.normalize import normalize, normalize_title
from stock_analyzer.ingest.parse_md import Paragraph, ParsedReport

log = logging.getLogger(__name__)

STRUCTURE_VERSION = "1"

NodeKind = Literal["chapter", "section", "subsection", "note", "auditor_report", "statement", "other"]
Chapter = Literal["business", "directors", "financials", "additional", "governance", "other"]
MAIN_CHAPTERS: tuple[Chapter, ...] = ("business", "directors", "financials", "additional", "governance")

CHAPTER_TITLES_HE: dict[str, str] = {
    "business": "תיאור עסקי התאגיד",
    "directors": "דוח הדירקטוריון",
    "financials": "דוחות כספיים",
    "additional": "פרטים נוספים על התאגיד",
    "governance": "אפקטיביות הבקרה הפנימית והצהרות מנהלים",
    "other": "אחר",
}


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

_ORDINALS = {
    "ראשון": 1,
    "שני": 2,
    "שלישי": 3,
    "רביעי": 4,
    "חמישי": 5,
    "שישי": 6,
    "שביעי": 7,
    "שמיני": 8,
}
_CHAPTER_ORDINAL = re.compile(r"^פרק\s+(ראשון|שני|שלישי|רביעי|חמישי|שישי|שביעי|שמיני)(?![א-ת])")
_ORDINALS_LONGEST_FIRST = sorted(_ORDINALS, key=len, reverse=True)


def chapter_ordinal(text: str) -> int | None:
    """The chapter ordinal of a heading like "פרק שלישי", tolerating a stray space inside
    the word ("פרק ש לישי"), which the provider's text extraction sometimes produces."""
    if m := _CHAPTER_ORDINAL.match(text):
        return _ORDINALS[m.group(1)]
    compact = re.sub(r"\s+", "", text[:24])
    if not compact.startswith("פרק"):
        return None
    rest = compact[3:]
    for word in _ORDINALS_LONGEST_FIRST:
        if rest.startswith(word):
            return _ORDINALS[word]
    return None


_CHAPTER_TITLE_MARKERS: tuple[tuple[str, Chapter], ...] = (
    ("תיאור עסקי", "business"),
    ("דוח הדירקטוריון", "directors"),
    ("דוחות כספיים", "financials"),
    ("פרטים נוספים", "additional"),
    ("אפקטיביות הבקרה", "governance"),
    ("הצהרות מנהלים", "governance"),
)
_ORDINAL_DEFAULT: dict[int, Chapter] = {1: "business", 2: "directors", 3: "financials", 4: "additional"}
_TOC_HEADINGS = ("תוכן עניינים", "תוכן העניינים", "רשימת פרקים", "תוכן העניין")

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
        if any(t.startswith(h) for h in _TOC_HEADINGS) and len(t) < 40:
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


def find_chapters(
    paragraphs: list[Paragraph], toc_pages: set[int], warnings: list[str]
) -> tuple[list[_Start], list[str]]:
    starts: list[_Start] = []
    seen: dict[str, int] = {}
    duplicated: list[str] = []
    last_ordinal = 0
    for i, p in enumerate(paragraphs):
        if p.page_index in toc_pages or p.in_table or not _is_heading_like(p, max_len=90):
            continue
        t = _first_line(p)
        ordinal = chapter_ordinal(t)
        title_hint = t
        if ordinal is not None:
            # the chapter title is usually on the same line or the next short paragraph(s)
            hints: list[str] = []
            for q in paragraphs[i + 1 : i + 3]:
                if (
                    q.page_index != p.page_index
                    or q.in_table
                    or not (q.heading_level or len(_first_line(q)) <= 60)
                ):
                    break
                line = _first_line(q)
                # skip brand and footer-like lines ("MalamTeam", "www.x.com | חברה | 3")
                if re.search(r"[א-ת]", line) and not re.search(r"\||www\.|https?:", line):
                    hints.append(line)
            nxt = " ".join(hints)
            title_hint = f"{t} {nxt}"
        else:
            # a title marker alone starts a chapter only if it is a real heading
            if not p.heading_level or not any(t.startswith(mk) for mk, _ in _CHAPTER_TITLE_MARKERS):
                continue
        kind: Chapter | None = next((ch for mk, ch in _CHAPTER_TITLE_MARKERS if mk in title_hint), None)
        if kind is None and ordinal is not None:
            kind = _ORDINAL_DEFAULT.get(ordinal, "other")
        if kind is None:
            continue
        if ordinal is not None and ordinal < last_ordinal:
            continue  # a cross-reference to an earlier chapter
        key = f"{kind}:{ordinal}" if kind == "other" else kind
        if key in seen:
            # the same chapter again: a cover page followed by its first page is normal;
            # after another chapter started it is a real duplicate
            if starts and starts[-1].chapter != kind:
                duplicated.append(kind)
                warnings.append(f"chapter {kind!r} found again on page {p.page_index}")
            continue
        seen[key] = p.seq
        last_ordinal = ordinal or last_ordinal
        title = CHAPTER_TITLES_HE[kind] if kind != "other" else normalize_title(title_hint)[:80]
        node_id = kind if kind != "other" else f"chapter-{ordinal or len(starts) + 1}"
        starts.append(_Start(node_id, "chapter", kind, str(ordinal) if ordinal else None, title, 1, p.seq))
    return starts, duplicated


# ---------------------------------------------------------------- business sections


_MATRES = re.compile(r"(?<=[א-ת])[וי]+")
_EDGE_PREFIX = re.compile(r"^(?:\.?\d{1,2}(?:\.\d{1,3})*\.?|[א-ת]['׳]?\.)\s*")
_EDGE_SUFFIX = re.compile(r"\s*\.?\d{1,2}(?:\.\d{1,3})*\.?$")


def match_key(text: str) -> str:
    """Spelling-insensitive key for fuzzy title matching: Hebrew plene/defective spellings
    (שירותי/שרותי, חיסכון/חסכון) agree once vav/yod inside a word are dropped.
    Same length class as the input is not preserved, so match on keys of both sides."""
    return _MATRES.sub("", text)


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

    chapter_starts, duplicated = find_chapters(paras, toc_pages, warnings)
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
