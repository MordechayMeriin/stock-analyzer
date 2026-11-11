"""Filing services: annual filings with the selected report and cached status; fetching."""

from __future__ import annotations

from collections.abc import Iterable

from stock_analyzer.companies import resolve_ticker
from stock_analyzer.errors import ReportSelectionError
from stock_analyzer.ingest.fr_client import Filing, load_report, save_report
from stock_analyzer.ingest.select import filing_fiscal_year, select_report
from stock_analyzer.services.context import Ctx
from stock_analyzer.services.models import FetchedReport, FetchOut, FilingOut, FilingsOut, FiscalYearFilings


def cached_filing_id(ctx: Ctx, ticker: str, fiscal_year: int) -> int | None:
    return ctx.store.cached_filing_id(ticker.upper(), fiscal_year)


def company_filings(ctx: Ctx, ticker: str) -> list[Filing]:
    company = resolve_ticker(ctx.settings.companies_file, ticker)
    return ctx.fr.list_filings(company.fr_company_id)


def list_filings(ctx: Ctx, ticker: str) -> FilingsOut:
    company = resolve_ticker(ctx.settings.companies_file, ticker)
    filings = ctx.fr.list_filings(company.fr_company_id)
    years = sorted({y for f in filings if (y := filing_fiscal_year(f)) is not None}, reverse=True)
    out: list[FiscalYearFilings] = []
    for year in years:
        in_year = [f for f in filings if filing_fiscal_year(f) == year]
        try:
            selected: Filing | None = select_report(in_year, year, ticker=company.ticker)
            error = None
        except ReportSelectionError as exc:
            selected, error = None, exc.message
        cached_id = cached_filing_id(ctx, company.ticker, year)
        out.append(
            FiscalYearFilings(
                fiscal_year=year,
                selected_filing_id=selected.id if selected else None,
                selection_error=error,
                report_cached=selected is not None and cached_id == selected.id,
                filings=[
                    FilingOut(
                        filing_id=f.id,
                        title=f.title,
                        fiscal_year=year,
                        release_datetime=f.release_datetime,
                        file_extension=f.file_extension,
                        file_size=f.file_size,
                        document_url=f.url,
                        viewer_url=f.viewer_url,
                        selected=selected is not None and f.id == selected.id,
                        cached=cached_id == f.id,
                    )
                    for f in in_year
                ],
            )
        )
    return FilingsOut(ticker=company.ticker, years=out)


def fetch(ctx: Ctx, ticker: str, years: Iterable[int], *, financials: bool = True) -> FetchOut:
    """Fetch and save the selected report of each year (and the financials). Live mode."""
    company = resolve_ticker(ctx.settings.companies_file, ticker)
    filings = ctx.fr.list_filings(company.fr_company_id)
    reports: list[FetchedReport] = []
    for year in years:
        filing = select_report(filings, year, ticker=company.ticker)
        existing = load_report(ctx.settings, company.ticker, year, store=ctx.store)
        if existing and existing[1].filing_id == filing.id and not ctx.refresh:
            text, meta = existing
        else:
            text = ctx.fr.get_markdown(filing.id)
            meta = save_report(ctx.settings, company.ticker, year, filing, text, store=ctx.store)
        reports.append(
            FetchedReport(
                fiscal_year=year,
                filing_id=filing.id,
                total_chars=meta.total_chars,
                path=ctx.store.report_location(company.ticker, year),
            )
        )
    saved = False
    if financials:
        for revisions in (False, True):
            data = ctx.fr.get_financials(company.fr_company_id, revisions=revisions)
            ctx.store.save_financials(company.ticker, revisions, data)
        saved = True
    return FetchOut(
        ticker=company.ticker,
        reports=reports,
        financials_saved=saved,
        credits_used=ctx.fr.credits_used,
        network_calls=ctx.fr.network_calls,
    )
