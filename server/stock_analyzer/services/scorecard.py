"""Coverage scorecard over stored reports (report-parsing spec: Coverage scorecard).

Parses every stored report (or the ones named) straight from the state store and summarizes the
structure coverage, one row per report. Stored data only: no provider calls, no credits.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager

from pydantic import BaseModel

from stock_analyzer.ingest.parse_md import parse_report
from stock_analyzer.ingest.structure import build_structure
from stock_analyzer.services.context import Ctx


class ScoreRow(BaseModel):
    ticker: str
    fiscal_year: int
    pages: int = 0
    pages_printed: int = 0
    chapters_found: list[str] = []
    chapters_missing: list[str] = []
    chapters_duplicated: list[str] = []
    business_sections: int = 0
    business_toc_entries: int = 0
    business_toc_matched: int = 0
    business_sections_source: str = "toc"
    notes: int = 0
    statements: int = 0
    warnings: int = 0
    seconds: float = 0.0
    error: str | None = None


def score_report(ctx: Ctx, ticker: str, fiscal_year: int) -> ScoreRow:
    row = ScoreRow(ticker=ticker.upper(), fiscal_year=fiscal_year)
    started = time.perf_counter()
    try:
        loaded = ctx.store.load_report(ticker, fiscal_year)
        if loaded is None:
            raise LookupError(f"no stored report for {ticker.upper()} FY{fiscal_year}")
        text, meta = loaded
        parsed = parse_report(
            text, ticker=ticker, fiscal_year=fiscal_year, filing_id=meta.filing_id, settings=ctx.settings
        )
        structure = build_structure(parsed, ctx.settings)
    except Exception as exc:  # a scorecard reports every failure instead of stopping at the first
        row.error = f"{type(exc).__name__}: {exc}"
        row.seconds = round(time.perf_counter() - started, 2)
        return row
    c = structure.coverage
    row.pages = parsed.page_count
    row.pages_printed = sum(1 for p in parsed.pages if p.printed is not None)
    row.chapters_found = c.chapters_found
    row.chapters_missing = c.chapters_missing
    row.chapters_duplicated = c.chapters_duplicated
    row.business_sections = c.business_sections
    row.business_toc_entries = c.business_toc_entries
    row.business_toc_matched = c.business_sections_matched_from_toc
    row.business_sections_source = c.business_sections_source
    row.notes = c.notes
    row.statements = c.statements
    row.warnings = len(structure.warnings) + len(parsed.warnings)
    row.seconds = round(time.perf_counter() - started, 2)
    return row


@contextmanager
def _quiet_parser():
    """The parser logs each warning; the scorecard counts them per row instead."""
    logger = logging.getLogger("stock_analyzer.ingest")
    level = logger.level
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logger.setLevel(level)


def scorecard(ctx: Ctx, ticker: str | None = None, fiscal_year: int | None = None) -> list[ScoreRow]:
    """One row per stored report, filtered by ticker and fiscal year when given."""
    targets = [
        (t, y)
        for t, y in ctx.store.list_reports()
        if (ticker is None or t == ticker.upper()) and (fiscal_year is None or y == fiscal_year)
    ]
    if ticker is not None and fiscal_year is not None and not targets:
        targets = [(ticker.upper(), fiscal_year)]  # reported as an error row: nothing stored
    with _quiet_parser():
        return [score_report(ctx, t, y) for t, y in targets]
