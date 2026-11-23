"""Report Markdown → paragraphs with pages (plan.md §1.4, report-parsing spec).

Pipeline: detect the page style → split pages → record each page's head → find footers and
printed page numbers → strip footers, picture-text blocks, lines repeated on more than
``repeated_line_ratio`` of pages and running headers/footers at page edges → split on blank
lines (a whole table is one paragraph, headings stand alone) → normalize.

A page is a page of the provider's Markdown, not of the source PDF: the provider sometimes
splits one printed page into several Markdown pages, so the page index is a position in the
report file and nothing links to the PDF. The printed page number comes from the footer.

Styles seen in provider Markdown (sometimes within one company):
- **A**: ``<!-- page N -->`` markers (absolute page numbers), footers like
  ``www.malamteam.com **|** מלם תים בע"מ **| 55 |**``, picture-text blocks.
- **B**: pages separated by a bare ``---`` line (not a table divider), footers like
  ``www.malamteam.com | מלם תים בע"מ | 57`` or a bare number, repeated page headers.
  A ``---`` followed by footnotes, inside a page without a footer before it, is a footnote
  rule, not a page break.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from stock_analyzer.config import Settings
from stock_analyzer.errors import ParseError
from stock_analyzer.ingest.normalize import normalize, normalize_title

log = logging.getLogger(__name__)

PARSER_VERSION = "2"

Style = Literal["A", "B"]

_PAGE_MARKER = re.compile(r"<!--\s*page\s+(\d+)\s*-->")
_PIC_START = "<!-- Start of picture text -->"
_PIC_END = "<!-- End of picture text -->"
_COMMENT_ONLY = re.compile(r"^\s*<!--.*?-->\s*$")
_IMAGE = re.compile(r"^\s*!\[[^\]]*\]\([^)]*\)\s*$")
_FOOTNOTE_START = re.compile(r"^\s*(?:[¹²³⁴⁵⁶⁷⁸⁹⁰]+|\*{1,3}\s|\(\d{1,2}\)\s)")
_PIPE_NUMBER = re.compile(r"\|\s*(\d{1,4})\s*(?=\||$)")
_BARE_NUMBER = re.compile(r"^\s*(\d{1,3})\s*$")
_DASH_NUMBER = re.compile(r"^\s*[-–]\s*(\d{1,3})\s*[-–]\s*$")
_TRAILING_NUMBER = re.compile(r"[א-ת)]\s+(\d{1,3})\s*\|?\s*$")
_HEADING = re.compile(r"^\s*(#{1,6})\s+\S")


class Paragraph(BaseModel):
    pid: str  # f"{ticker}-{fy}-p{page_index:04d}-{n:03d}"
    seq: int  # position in the report (0-based), used for node paragraph ranges
    fiscal_year: int
    filing_id: int
    page_index: int  # page in the original document → citation links (#page=N)
    page_printed: int | None
    char_start: int
    char_end: int
    raw: str
    text: str  # normalized
    heading_level: int  # 0 = body
    in_table: bool


class PageInfo(BaseModel):
    index: int
    printed: int | None
    char_start: int
    char_end: int
    # the page's first content lines before footer/running-line stripping (chapter openers are
    # read from here); images, comments, table rows and logo OCR (short Latin-only lines) excluded
    head: list[str] = []
    running_header: str | None = None  # running header/footer line removed from this page


class ParsedReport(BaseModel):
    ticker: str
    fiscal_year: int
    filing_id: int
    style: Style
    parser_version: str = PARSER_VERSION
    pages: list[PageInfo]
    paragraphs: list[Paragraph]
    numbering_restarts: list[int]  # pages where the printed number does not increase
    repeated_lines: list[str]
    warnings: list[str] = []

    @property
    def page_count(self) -> int:
        return len(self.pages)


# ---------------------------------------------------------------- internals


@dataclass
class _Line:
    text: str
    start: int  # offset of the line in the source

    @property
    def end(self) -> int:
        return self.start + len(self.text)


@dataclass
class _Page:
    index: int
    start: int
    end: int
    lines: list[_Line] = field(default_factory=list)
    printed: int | None = None
    head: list[str] = field(default_factory=list)
    running_header: str | None = None
    footer_lines: list[str] = field(default_factory=list)  # normalized lines the footer consumed


def _lines(text: str, start: int, end: int) -> list[_Line]:
    out: list[_Line] = []
    pos = start
    for chunk in text[start:end].split("\n"):
        out.append(_Line(chunk, pos))
        pos += len(chunk) + 1
    return out


def _is_table_line(line: str) -> bool:
    return line.lstrip().startswith("|")


def _is_table_block(block: list[_Line]) -> bool:
    """A block is a table when it starts with a "|" line and some row closes with "|"."""
    return _is_table_line(block[0].text) and any(ln.text.rstrip().endswith("|") for ln in block)


def _is_page_rule(line: str) -> bool:
    return line.strip() == "---"


def detect_style(text: str) -> Style:
    if len(_PAGE_MARKER.findall(text)) >= 2:
        return "A"
    if sum(1 for line in text.split("\n") if _is_page_rule(line)) >= 1:
        return "B"
    raise ParseError("unknown page style: neither <!-- page N --> markers nor '---' page separators found")


def _split_a(text: str) -> list[_Page]:
    markers = list(_PAGE_MARKER.finditer(text))
    pages: list[_Page] = []
    for i, m in enumerate(markers):
        start = m.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        if i == 0 and text[: m.start()].strip():
            start = 0  # stray text before the first marker belongs to the first page
        pages.append(_Page(index=int(m.group(1)), start=start, end=end))
    return pages


def _split_b(text: str) -> list[_Page]:
    lines = _lines(text, 0, len(text))
    pages: list[_Page] = []
    seg_start = 0
    seg_lines: list[_Line] = []
    for i, line in enumerate(lines):
        if _is_page_rule(line.text):
            nxt = next((n.text for n in lines[i + 1 :] if n.text.strip()), "")
            if _FOOTNOTE_START.match(nxt) and not _footer(seg_lines)[0]:
                seg_lines.append(line)  # footnote rule inside a page
                continue
            pages.append(_Page(index=len(pages) + 1, start=seg_start, end=line.start))
            seg_start = line.end + 1
            seg_lines = []
            continue
        seg_lines.append(line)
    pages.append(_Page(index=len(pages) + 1, start=seg_start, end=len(text)))
    return pages


def _table_rows(lines: list[_Line]) -> set[int]:
    """Positions of lines that are rows of a multi-line Markdown table block. A row's cell text
    can wrap, so a continuation line ends with "|" without starting with one."""
    rows: set[int] = set()
    block: list[int] = []

    def close() -> None:
        if len(block) >= 2 and _is_table_line(lines[block[0]].text):
            rows.update(
                i for i in block if _is_table_line(lines[i].text) or lines[i].text.rstrip().endswith("|")
            )
        block.clear()

    for i, ln in enumerate(lines):
        if ln.text.strip():
            block.append(i)
        else:
            close()
    close()
    return rows


def _running_like(norm: str) -> bool:
    """A running header/footer line such as "פרק א | תיאור עסקי התאגיד": short, has "|" and
    letters, and no number."""
    return "|" in norm and len(norm) <= 90 and bool(re.search(r"[א-ת]", norm)) and not re.search(r"\d", norm)


def _footer(lines: list[_Line]) -> tuple[list[int], int | None]:
    """(positions in ``lines`` of the footer lines, printed number) among the last lines.

    Layouts (report-parsing spec: Page footer layouts): ``site | name | N``; a bare number on the
    last line; a bare number followed by running-header lines; ``- N -``; a ``title | title N``
    line. Numbers in table rows are never page numbers."""
    nonempty = [i for i, ln in enumerate(lines) if ln.text.strip()]
    tail = nonempty[-3:]
    rows = _table_rows(lines)

    def neighbour(i: int, step: int) -> str:
        k = nonempty.index(i) + step
        return lines[nonempty[k]].text if 0 <= k < len(nonempty) else ""

    for i in reversed(tail):
        raw = lines[i].text
        if _HEADING.match(raw) or i in rows:
            continue
        norm = normalize(raw)
        later = [j for j in tail if j > i]
        if m := _DASH_NUMBER.match(norm):
            if not later:
                return [i], int(m.group(1))
            continue
        if "|" in norm:
            letters = re.search(r"[A-Za-z֐-׿]", norm)
            nums = [int(n) for n in _PIPE_NUMBER.findall(norm) if not 1900 <= int(n) <= 2100]
            if letters and nums:
                return [i], nums[-1]
            if letters and (m := _TRAILING_NUMBER.search(norm)) and not 1900 <= int(m.group(1)) <= 2100:
                return [i], int(m.group(1))  # "פרק א | תיאור עסקי התאגיד 46"
            continue
        m = _BARE_NUMBER.match(norm)
        if not m:
            continue
        # a bare number ending a numbered list ("16 ...", then "17") is a list item, not a footer
        if re.match(r"^\s*\d{1,3}[.)]?\s+\S", neighbour(i, -1)):
            continue
        if not later:
            return [i], int(m.group(1))
        if all(_running_like(normalize(lines[j].text)) for j in later):
            return [i, *later], int(m.group(1))  # "49" above "פרק א | תיאור עסקי התאגיד"
    return [], None


_LOGO_OCR = re.compile(r"^[A-Za-z][A-Za-z .\-]{0,24}$")
HEAD_LINES = 6


def _page_head(lines: list[_Line]) -> list[str]:
    """First content lines of a page: no table rows, no logo OCR ("ELYAL", "EVALUATION") and no
    lines without letters."""
    head: list[str] = []
    for ln in lines:
        if not ln.text.strip() or _is_table_line(ln.text):
            continue
        text = normalize_title(ln.text)
        if not text or _LOGO_OCR.match(text) or not re.search(r"[A-Za-zא-ת]", text):
            continue
        head.append(text)
        if len(head) == HEAD_LINES:
            break
    return head


RUNNING_EDGE = 3  # lines at each edge of a page that can be running headers/footers
RUNNING_MAX_CHARS = 90
_EDGE_NUMBERS = re.compile(r"^(?:\d{1,4}\s+)+|(?:\s+\d{1,4})+\s*\|?$")


def _running_key(text: str) -> str:
    """Key that ignores numbers glued to either end ("פרק א | תיאור עסקי התאגיד 46",
    "2025 פרק ג | …"), so a running line matches its numberless form; inner numbers count."""
    return " ".join(_EDGE_NUMBERS.sub(" ", normalize(text)).split()).strip(" -–|")


def _running_candidate(text: str) -> bool:
    """Short, has letters, and is not a sentence (running lines do not end with "." or ":")."""
    return (
        len(text) <= RUNNING_MAX_CHARS
        and len(_running_key(text)) >= 3  # never a lone letter ("א"), which can mark a subsection
        and not text.rstrip().endswith((".", ":"))
        and bool(re.search(r"[A-Za-zא-ת]", text))
    )


def _edge_positions(lines: list[_Line]) -> list[int]:
    content = [i for i, ln in enumerate(lines) if ln.text.strip() and not _is_table_line(ln.text)]
    return sorted(set(content[:RUNNING_EDGE] + content[-RUNNING_EDGE:]))


def _strip_running_lines(pages: list[_Page], min_pages: int) -> None:
    """Remove running headers/footers: short lines at a page edge on at least ``min_pages`` pages.
    Each page records the (first) running line removed from it."""
    edges = {p.index: _edge_positions(p.lines) for p in pages}
    counts: Counter[str] = Counter()
    for p in pages:
        keys = set()
        # footer lines sat at the page edge too ("פרק א | תיאור עסקי התאגיד 46" read as a footer)
        for text in [normalize(p.lines[i].text) for i in edges[p.index]] + p.footer_lines:
            if _running_candidate(text):
                keys.add(_running_key(text))
        counts.update(keys)
    running = {k for k, n in counts.items() if n >= min_pages}
    if not running:
        return
    for p in pages:
        for text in p.footer_lines:
            if p.running_header is None and _running_candidate(text) and _running_key(text) in running:
                p.running_header = _running_key(text)
        drop = []
        for i in edges[p.index]:
            text = normalize(p.lines[i].text)
            if _running_candidate(text) and _running_key(text) in running:
                drop.append(i)
                if p.running_header is None:
                    p.running_header = _running_key(text).lstrip("#").strip()
        if drop:
            p.lines = [ln for k, ln in enumerate(p.lines) if k not in drop]


def _drop_pictures(lines: list[_Line]) -> list[_Line]:
    kept: list[_Line] = []
    in_pic = False
    for ln in lines:
        t = ln.text
        if in_pic:
            if _PIC_END in t:
                in_pic = False
            continue
        if _PIC_START in t:
            in_pic = _PIC_END not in t
            continue
        if _COMMENT_ONLY.match(t) or _IMAGE.match(t):
            continue
        kept.append(ln)
    return kept


def _numbering_restarts(pages: list[_Page]) -> list[int]:
    """Pages whose printed number does not increase over the previous numbered page (printed
    numbering restarts per chapter)."""
    restarts: list[int] = []
    prev: int | None = None
    for p in pages:
        if p.printed is None:
            continue
        if prev is not None and p.printed <= prev:
            restarts.append(p.index)
        prev = p.printed
    return restarts


def _blocks(lines: list[_Line]) -> list[list[_Line]]:
    """Split page lines into paragraph blocks: blank lines separate; headings stand alone;
    a table region (first '|' line to the last line ending in '|') is one block."""
    raw_blocks: list[list[_Line]] = []
    cur: list[_Line] = []
    for ln in lines:
        if not ln.text.strip():
            if cur:
                raw_blocks.append(cur)
                cur = []
            continue
        if _HEADING.match(ln.text):
            if cur:
                raw_blocks.append(cur)
            raw_blocks.append([ln])
            cur = []
            continue
        cur.append(ln)
    if cur:
        raw_blocks.append(cur)

    out: list[list[_Line]] = []
    for block in raw_blocks:
        first_tab = next((i for i, ln in enumerate(block) if _is_table_line(ln.text)), None)
        if first_tab is None:
            out.append(block)
            continue
        closing = [i for i, ln in enumerate(block) if i >= first_tab and ln.text.rstrip().endswith("|")]
        if not closing:
            out.append(block)  # a "|" line that never closes its row: plain text, not a table
            continue
        last_tab = closing[-1]
        if first_tab > 0:
            out.append(block[:first_tab])
        out.append(block[first_tab : last_tab + 1])
        if last_tab + 1 < len(block):
            out.append(block[last_tab + 1 :])
    return out


def _merge_tables_across_blanks(blocks: list[list[_Line]]) -> list[list[_Line]]:
    """A table interrupted only by blank lines stays one paragraph."""
    merged: list[list[_Line]] = []
    for b in blocks:
        if merged and _is_table_block(b) and _is_table_block(merged[-1]):
            merged[-1] = merged[-1] + b
        else:
            merged.append(b)
    return merged


# ---------------------------------------------------------------- public API


def parse_report(
    text: str,
    *,
    ticker: str,
    fiscal_year: int,
    filing_id: int,
    settings: Settings | None = None,
) -> ParsedReport:
    settings = settings or Settings()
    style = detect_style(text)
    pages = _split_a(text) if style == "A" else _split_b(text)
    if not pages:
        raise ParseError("no pages found")
    warnings: list[str] = []

    # per-page cleanup: pictures, footers
    for p in pages:
        lines = _drop_pictures(_lines(text, p.start, p.end))
        p.head = _page_head(lines)
        footer, printed = _footer(lines)
        if footer:
            p.printed = printed
            p.footer_lines = [normalize(lines[k].text) for k in footer]
            lines = [ln for k, ln in enumerate(lines) if k not in footer]
        p.lines = lines

    # repeated lines (page headers etc.), never table rows
    repeated: set[str] = set()
    if len(pages) >= settings.repeated_line_min_pages:
        counts: Counter[str] = Counter()
        for p in pages:
            counts.update(
                {normalize(ln.text) for ln in p.lines if ln.text.strip() and not _is_table_line(ln.text)}
            )
        limit = settings.repeated_line_ratio * len(pages)
        repeated = {line for line, n in counts.items() if line and n > limit}

    # running headers/footers at page edges, below the global threshold
    _strip_running_lines(pages, settings.running_line_min_pages)

    paragraphs: list[Paragraph] = []
    for p in pages:
        lines = [ln for ln in p.lines if not (ln.text.strip() and normalize(ln.text) in repeated)]
        n = 0
        for block in _merge_tables_across_blanks(_blocks(lines)):
            raw = "\n".join(ln.text for ln in block)
            in_table = _is_table_block(block)
            norm = normalize(raw, keep_newlines=in_table)
            if not norm:
                continue
            heading = _HEADING.match(block[0].text) if len(block) == 1 else None
            if heading:
                norm = norm.lstrip("#").strip()
                if not norm:
                    continue
            n += 1
            paragraphs.append(
                Paragraph(
                    pid=f"{ticker.upper()}-{fiscal_year}-p{p.index:04d}-{n:03d}",
                    seq=len(paragraphs),
                    fiscal_year=fiscal_year,
                    filing_id=filing_id,
                    page_index=p.index,
                    page_printed=p.printed,
                    char_start=block[0].start,
                    char_end=block[-1].end,
                    raw=raw,
                    text=norm,
                    heading_level=len(heading.group(1)) if heading else 0,
                    in_table=in_table,
                )
            )

    return ParsedReport(
        ticker=ticker.upper(),
        fiscal_year=fiscal_year,
        filing_id=filing_id,
        style=style,
        pages=[
            PageInfo(
                index=p.index,
                printed=p.printed,
                char_start=p.start,
                char_end=p.end,
                head=p.head,
                running_header=p.running_header,
            )
            for p in pages
        ],
        paragraphs=paragraphs,
        numbering_restarts=_numbering_restarts(pages),
        repeated_lines=sorted(repeated),
        warnings=warnings,
    )
