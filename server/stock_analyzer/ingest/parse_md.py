"""Report Markdown → page-cited paragraphs (plan.md §1.4, report-parsing spec).

Pipeline: detect the page style → split pages (page index = PDF page) → find footers and
printed page numbers → check the printed/index offset per numbering run → strip footers,
picture-text blocks and lines repeated on more than ``repeated_line_ratio`` of pages →
split on blank lines (a whole table is one paragraph, headings stand alone) → normalize.

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
from stock_analyzer.ingest.normalize import normalize

log = logging.getLogger(__name__)

PARSER_VERSION = "1"

Style = Literal["A", "B"]

_PAGE_MARKER = re.compile(r"<!--\s*page\s+(\d+)\s*-->")
_PIC_START = "<!-- Start of picture text -->"
_PIC_END = "<!-- End of picture text -->"
_COMMENT_ONLY = re.compile(r"^\s*<!--.*?-->\s*$")
_IMAGE = re.compile(r"^\s*!\[[^\]]*\]\([^)]*\)\s*$")
_FOOTNOTE_START = re.compile(r"^\s*(?:[¹²³⁴⁵⁶⁷⁸⁹⁰]+|\*{1,3}\s|\(\d{1,2}\)\s)")
_PIPE_NUMBER = re.compile(r"\|\s*(\d{1,4})\s*(?=\||$)")
_BARE_NUMBER = re.compile(r"^\s*(\d{1,3})\s*$")
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


class OffsetRun(BaseModel):
    first_page: int
    last_page: int
    offset: int  # page_index - page_printed


class OffsetIssue(BaseModel):
    page: int
    printed: int
    expected_printed: int


class ParsedReport(BaseModel):
    ticker: str
    fiscal_year: int
    filing_id: int
    style: Style
    parser_version: str = PARSER_VERSION
    pages: list[PageInfo]
    paragraphs: list[Paragraph]
    offset_runs: list[OffsetRun]
    numbering_restarts: list[int]  # pages where printed numbering restarts
    offset_issues: list[OffsetIssue]
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


def _lines(text: str, start: int, end: int) -> list[_Line]:
    out: list[_Line] = []
    pos = start
    for chunk in text[start:end].split("\n"):
        out.append(_Line(chunk, pos))
        pos += len(chunk) + 1
    return out


def _is_table_line(line: str) -> bool:
    return line.lstrip().startswith("|")


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
            if _FOOTNOTE_START.match(nxt) and _footer(seg_lines)[0] is None:
                seg_lines.append(line)  # footnote rule inside a page
                continue
            pages.append(_Page(index=len(pages) + 1, start=seg_start, end=line.start))
            seg_start = line.end + 1
            seg_lines = []
            continue
        seg_lines.append(line)
    pages.append(_Page(index=len(pages) + 1, start=seg_start, end=len(text)))
    return pages


def _footer(lines: list[_Line]) -> tuple[int | None, int | None]:
    """(position in ``lines`` of the footer line, printed number) among the last lines."""
    nonempty = [i for i, ln in enumerate(lines) if ln.text.strip()]
    tail = nonempty[-3:]

    def neighbour(i: int, step: int) -> str:
        k = nonempty.index(i) + step
        return lines[nonempty[k]].text if 0 <= k < len(nonempty) else ""

    for i in reversed(tail):
        raw = lines[i].text
        if _HEADING.match(raw):
            continue
        norm = normalize(raw)
        if "|" in norm:
            # a row inside a Markdown table (a table line next to another) is not a footer
            if _is_table_line(raw) and (_is_table_line(neighbour(i, -1)) or _is_table_line(neighbour(i, 1))):
                continue
            letters = re.search(r"[A-Za-z֐-׿]", norm)
            nums = [int(n) for n in _PIPE_NUMBER.findall(norm) if not 1900 <= int(n) <= 2100]
            if letters and nums:
                return i, nums[-1]
            continue
        m = _BARE_NUMBER.match(norm)
        # a bare number ending a numbered list ("16 ...", then "17") is a list item, not a footer
        if m and i == tail[-1] and not re.match(r"^\s*\d{1,3}[.)]?\s+\S", neighbour(i, -1)):
            return i, int(m.group(1))
    return None, None


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


def _check_offsets(pages: list[_Page]) -> tuple[list[OffsetRun], list[int], list[OffsetIssue]]:
    runs: list[OffsetRun] = []
    restarts: list[int] = []
    issues: list[OffsetIssue] = []
    prev_printed: int | None = None
    for p in pages:
        if p.printed is None:
            continue
        offset = p.index - p.printed
        if runs and prev_printed is not None and p.printed >= prev_printed and offset == runs[-1].offset:
            runs[-1].last_page = p.index
        elif runs and prev_printed is not None and p.printed > prev_printed:
            # numbering continues upward but the offset moved: an inconsistency within the run
            issues.append(
                OffsetIssue(page=p.index, printed=p.printed, expected_printed=p.index - runs[-1].offset)
            )
        else:
            if runs:
                restarts.append(p.index)
            runs.append(OffsetRun(first_page=p.index, last_page=p.index, offset=offset))
        prev_printed = p.printed
    return runs, restarts, issues


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
        last_tab = max(i for i, ln in enumerate(block) if ln.text.rstrip().endswith("|"))
        if last_tab < first_tab:
            out.append(block)
            continue
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
        if merged and _is_table_line(b[0].text) and _is_table_line(merged[-1][0].text):
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
        pos, printed = _footer(lines)
        if pos is not None:
            p.printed = printed
            lines = lines[:pos] + lines[pos + 1 :]
        p.lines = lines

    runs, restarts, issues = _check_offsets(pages)
    for issue in issues:
        log.warning(
            "%s FY%s: printed page %s on page %s, expected %s",
            ticker,
            fiscal_year,
            issue.printed,
            issue.page,
            issue.expected_printed,
        )
        warnings.append(f"page {issue.page}: printed {issue.printed}, expected {issue.expected_printed}")

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

    paragraphs: list[Paragraph] = []
    for p in pages:
        lines = [ln for ln in p.lines if not (ln.text.strip() and normalize(ln.text) in repeated)]
        n = 0
        for block in _merge_tables_across_blanks(_blocks(lines)):
            raw = "\n".join(ln.text for ln in block)
            in_table = _is_table_line(block[0].text)
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
        pages=[PageInfo(index=p.index, printed=p.printed, char_start=p.start, char_end=p.end) for p in pages],
        paragraphs=paragraphs,
        offset_runs=runs,
        numbering_restarts=restarts,
        offset_issues=issues,
        repeated_lines=sorted(repeated),
        warnings=warnings,
    )
