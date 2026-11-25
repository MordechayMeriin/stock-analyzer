"""Filing services: annual filings with the selected report and cached status; fetching."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from stock_analyzer.companies import TrackedCompany
from stock_analyzer.errors import ProviderNotFound, ReportNotProcessed, ReportSelectionError
from stock_analyzer.ingest.fr_client import Filing, load_report, save_report
from stock_analyzer.ingest.select import filing_fiscal_year, is_ready, markdown_availability, select_report
from stock_analyzer.services.companies import resolve_company
from stock_analyzer.services.context import Ctx
from stock_analyzer.services.models import FetchedReport, FetchOut, FilingOut, FilingsOut, FiscalYearFilings

# A cached filing list older than this is asked for again (live mode) when a needed year's report
# is still unprocessed at the provider. The provider's backfill moves over days to months.
LIST_REFRESH_AFTER = timedelta(hours=24)


def _waits_for_provider(filings: list[Filing], years: Iterable[int] | None, ticker: str) -> bool:
    """True when the selected report of any of ``years`` (all years if None) has no Markdown yet."""
    if years is None:
        years = {y for f in filings if (y := filing_fiscal_year(f)) is not None}
    for year in years:
        try:
            selected = select_report(filings, year, ticker=ticker)
        except ReportSelectionError:
            continue
        if not is_ready(selected):
            return True
    return False


def filings_for(ctx: Ctx, company: TrackedCompany, needed_years: Iterable[int] | None = None) -> list[Filing]:
    """The company's filings to select from.

    Read through the cache. In live mode, when a needed year's selected report is still processing
    (or failed) at the provider and the cached list is older than :data:`LIST_REFRESH_AFTER`, the
    list is fetched again once, replacing the cached copy. ``needed_years=None`` means every year.
    """
    filings = ctx.fr.list_filings(company.fr_company_id)
    if ctx.mode != "live" or ctx.refresh:  # cached mode never calls; refresh already re-fetched
        return filings
    years = None if needed_years is None else list(needed_years)
    if not _waits_for_provider(filings, years, company.ticker):
        return filings
    listed_at = ctx.fr.filings_cached_at(company.fr_company_id)
    if listed_at is None or datetime.now(UTC) - listed_at <= LIST_REFRESH_AFTER:
        return filings
    return ctx.fr.list_filings(company.fr_company_id, refresh=True)


def _not_processed(company: TrackedCompany, fiscal_year: int, filing: Filing) -> ReportNotProcessed:
    status = filing.processing_status or "no status"
    if markdown_availability(filing) == "failed":
        why = "the provider could not convert it to text"
    else:
        why = "the provider has not processed it yet, so its text is not available"
    return ReportNotProcessed(
        f"{company.ticker} FY{fiscal_year}: no Markdown for filing {filing.id} (provider status {status}): {why}"
    )


def fetch_markdown(ctx: Ctx, company: TrackedCompany, fiscal_year: int, filing: Filing) -> str:
    """The selected filing's Markdown, or :class:`ReportNotProcessed` when the provider has none.

    A filing the provider marks processing or failed is refused without a call. A 404 for a filing
    that is not ``COMPLETED`` means the same; for a ``COMPLETED`` one it stays a provider not-found.
    """
    if not is_ready(filing):
        raise _not_processed(company, fiscal_year, filing)
    try:
        return ctx.fr.get_markdown(filing.id)
    except ProviderNotFound as exc:
        if markdown_availability(filing) == "available":
            raise
        raise _not_processed(company, fiscal_year, filing) from exc


def cached_filing_id(ctx: Ctx, ticker: str, fiscal_year: int) -> int | None:
    return ctx.store.cached_filing_id(ticker.upper(), fiscal_year)


def company_filings(ctx: Ctx, ticker: str) -> list[Filing]:
    company = resolve_company(ctx, ticker)
    return filings_for(ctx, company)


def list_filings(ctx: Ctx, ticker: str) -> FilingsOut:
    company = resolve_company(ctx, ticker)
    filings = filings_for(ctx, company)
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
                markdown_availability=markdown_availability(selected) if selected is not None else None,
                filings=[
                    FilingOut(
                        filing_id=f.id,
                        title=f.title,
                        fiscal_year=year,
                        release_datetime=f.release_datetime,
                        file_extension=f.file_extension,
                        file_size=f.file_size,
                        selected=selected is not None and f.id == selected.id,
                        cached=cached_id == f.id,
                        processing_status=f.processing_status,
                    )
                    for f in in_year
                ],
            )
        )
    return FilingsOut(ticker=company.ticker, years=out)


def fetch(ctx: Ctx, ticker: str, years: Iterable[int], *, financials: bool = True) -> FetchOut:
    """Fetch and save the selected report of each year (and the financials). Live mode."""
    company = resolve_company(ctx, ticker)
    years = list(years)
    filings = filings_for(ctx, company, years)
    reports: list[FetchedReport] = []
    for year in years:
        filing = select_report(filings, year, ticker=company.ticker)
        existing = load_report(ctx.settings, company.ticker, year, store=ctx.store)
        if existing and existing[1].filing_id == filing.id and not ctx.refresh:
            text, meta = existing
        else:
            text = fetch_markdown(ctx, company, year, filing)
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
