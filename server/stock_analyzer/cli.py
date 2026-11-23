"""Command-line interface (typer). Thin adapter over ``services`` (design D4).

Commands: fetch, usage, structure, parse-check, fin-raw, companies list|add|remove, db init.
"""

from __future__ import annotations

import json
import sys
from typing import Annotated

import typer

from stock_analyzer.config import MissingCredential, get_settings
from stock_analyzer.errors import AnalyzerError
from stock_analyzer.services.context import Ctx

app = typer.Typer(add_completion=False, no_args_is_help=True, help="The Committee — report analyzer CLI")


def _ctx(mode: str = "cached", refresh: bool = False) -> Ctx:
    return Ctx(get_settings(), mode=mode, refresh=refresh)  # type: ignore[arg-type]


def _fail(exc: Exception) -> None:
    code = getattr(exc, "code", "error")
    typer.secho(f"error [{code}]: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


ModeOpt = Annotated[str, typer.Option("--mode", help="cached (local data only) or live")]


@app.command()
def fetch(
    ticker: str,
    years: Annotated[list[int], typer.Argument(help="Fiscal years, e.g. 2024 2025")],
    refresh: Annotated[bool, typer.Option("--refresh", help="Bypass the cache and re-download")] = False,
    no_financials: Annotated[
        bool, typer.Option("--no-financials", help="Skip the financials (40 credits each)")
    ] = False,
) -> None:
    """Fetch the selected annual report of each year, plus the company's financials (live)."""
    from stock_analyzer.services import filings

    try:
        ctx = _ctx("live", refresh)
        result = filings.fetch(ctx, ticker, years, financials=not no_financials)
    except (AnalyzerError, MissingCredential, ValueError) as exc:
        _fail(exc)
        return
    for r in result.reports:
        typer.echo(
            f"{result.ticker} FY{r.fiscal_year}: filing {r.filing_id}, {r.total_chars:,} chars → {r.path}"
        )
    if result.financials_saved:
        typer.echo(f"{result.ticker}: financials saved (with and without revisions)")
    typer.echo(f"credits used this run: {result.credits_used} ({result.network_calls} network calls)")


@app.command()
def usage(mode: ModeOpt = "live") -> None:
    """Provider credit usage and LLM spend from the logs."""
    from stock_analyzer.services import usage as usage_service

    try:
        out = usage_service.usage(_ctx(mode))
    except (AnalyzerError, ValueError) as exc:
        _fail(exc)
        return
    json.dump(out.model_dump(mode="json"), sys.stdout, ensure_ascii=False, indent=2)
    typer.echo()


companies_app = typer.Typer(no_args_is_help=True, help="Tracked companies (companies.yaml plus added ones)")
app.add_typer(companies_app, name="companies")


@companies_app.command("list")
def companies_list() -> None:
    """Tracked companies with their source: registry (companies.yaml) or added (state store)."""
    from stock_analyzer.services import companies

    try:
        rows = companies.list_tracked(_ctx())
    except AnalyzerError as exc:
        _fail(exc)
        return
    for c in rows:
        typer.echo(
            f"{c.ticker:<10} {c.fr_company_id:>8}  {c.source:<8}  {c.name_he}  {c.name_en or ''}".rstrip()
        )


@companies_app.command("add")
def companies_add(
    fr_id: Annotated[int, typer.Option("--fr-id", help="Provider company id (from search)")],
    ticker: Annotated[str, typer.Option("--ticker", help="Exchange ticker, stored upper-case")],
    name_he: Annotated[str, typer.Option("--name-he", help="Hebrew name")],
    name_en: Annotated[str | None, typer.Option("--name-en", help="English name")] = None,
    isin: Annotated[str | None, typer.Option("--isin", help="ISIN")] = None,
) -> None:
    """Start tracking a company (live mode; writes to the active state store). Nothing is fetched."""
    from pydantic import ValidationError

    from stock_analyzer.services import companies
    from stock_analyzer.services.models import AddCompanyIn

    try:
        body = AddCompanyIn(fr_company_id=fr_id, ticker=ticker, name_he=name_he, name_en=name_en, isin=isin)
        out = companies.add(_ctx("live"), body)
    except ValidationError as exc:
        fields = ", ".join(str(e["loc"][0]) for e in exc.errors())
        typer.secho(f"error [validation_error]: invalid {fields}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from None
    except (AnalyzerError, ValueError) as exc:
        _fail(exc)
        return
    typer.echo(f"now tracking {out.ticker} (provider company {out.fr_company_id}, {out.name_he})")


@companies_app.command("remove")
def companies_remove(ticker: str) -> None:
    """Stop tracking a company added at runtime (live mode). Cached data is kept."""
    from stock_analyzer.services import companies

    try:
        companies.remove(_ctx("live"), ticker)
    except (AnalyzerError, ValueError) as exc:
        _fail(exc)
        return
    typer.echo(f"stopped tracking {ticker.strip().upper()}; its cached data is kept")


db_app = typer.Typer(no_args_is_help=True, help="State store database (Postgres backend)")
app.add_typer(db_app, name="db")


@db_app.command("init")
def db_init() -> None:
    """Create the state-store schema in DATABASE_URL (idempotent; existing data is kept)."""
    from stock_analyzer import store as store_module
    from stock_analyzer.store.pg import PgStore

    settings = get_settings()
    if settings.database_url is None:
        typer.secho(
            "error [configuration_error]: DATABASE_URL is not set. `db init` creates the Postgres schema "
            "for the state store; without DATABASE_URL the server keeps its state in DATA_DIR, "
            "which needs no setup.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)
    store = store_module.get_store(settings)
    assert isinstance(store, PgStore)
    try:
        existed = store.init_schema()
    except AnalyzerError as exc:
        _fail(exc)
        return
    if existed:
        typer.echo(f"schema {store.schema!r} is already present; checked, existing data kept")
    else:
        typer.echo(
            f"created schema {store.schema!r}: kv_cache, reports, financials_snapshots, usage_log, "
            "tracked_companies"
        )


def render_structure(out) -> list[str]:
    """Text rendering of a structure tree, shared by the CLI and the parity test."""
    by_id = {n.node_id: n for n in out.nodes}
    lines: list[str] = []

    def walk(node_id: str, depth: int) -> None:
        n = by_id[node_id]
        printed = n.printed_pages
        pp = f" (printed {printed[0]}–{printed[1]})" if printed[0] is not None else ""
        number = f"{n.number} " if n.number and n.kind != "chapter" else ""
        lines.append(f"{'  ' * depth}{number}{n.title}  [p{n.pages[0]}–{n.pages[1]}{pp}]  #{n.node_id}")
        for child in n.children:
            walk(child, depth + 1)

    for root in out.roots:
        walk(root, 0)
    return lines


@app.command()
def structure(
    ticker: str,
    fiscal_year: int,
    mode: ModeOpt = "cached",
    depth: Annotated[int, typer.Option(help="Max tree depth to print (0 = all)")] = 0,
) -> None:
    """Print a report's structure tree with page ranges, then a coverage summary."""
    from stock_analyzer.services import reports

    try:
        out = reports.report_structure(_ctx(mode), ticker, fiscal_year)
    except (AnalyzerError, MissingCredential, ValueError) as exc:
        _fail(exc)
        return
    by_id = {n.node_id: n for n in out.nodes}
    for line in render_structure(out):
        node_id = line.rsplit("#", 1)[-1]
        if depth and by_id[node_id].level > depth:
            continue
        typer.echo(line)
    c = out.coverage.model_dump()
    typer.echo("")
    typer.echo(
        f"{out.ticker} FY{out.fiscal_year} — filing {out.filing_id}, {out.page_count} pages (style {out.page_style})"
    )
    typer.echo(
        f"chapters: {', '.join(c['chapters_found'])}"
        + (f" | missing: {', '.join(c['chapters_missing'])}" if c["chapters_missing"] else "")
        + (f" | duplicated: {', '.join(c['chapters_duplicated'])}" if c["chapters_duplicated"] else "")
    )
    typer.echo(
        f"business sections: {c['business_sections']} (TOC entries {c['business_toc_entries']}, matched "
        f"{c['business_sections_matched_from_toc']}; source: {c['business_sections_source']}), "
        f"subsections: {c['subsections']}"
    )
    typer.echo(
        f"directors' headings: {c['directors_headings']}, auditor's reports: {c['auditor_reports']}, "
        f"statements: {c['statements']}, notes: {c['notes']}"
        + (f" (no heading for {c['note_numbers_missing']})" if c["note_numbers_missing"] else "")
    )
    typer.echo(f"paragraphs in chapters: {c['paragraphs_in_chapters']}/{c['paragraphs']}")
    for warning in out.warnings:
        typer.secho(f"warning: {warning}", fg=typer.colors.YELLOW)


SCORE_HEADER = (
    f"{'TICKER':<7}{'FY':<6}{'PAGES':>6}{'PRINTED':>8}  {'CHAPTERS':<9}{'SECTIONS':>9}{'TOC':>8}"
    f"{'NOTES':>7}{'STMTS':>6}{'WARN':>6}{'SEC':>7}  MISSING / ERROR"
)


def render_score_row(row) -> str:
    """One scorecard line (shared by the CLI and its tests)."""
    head = f"{row.ticker:<7}{row.fiscal_year:<6}"
    if row.error:
        return f"{head}{'':>6}{'':>8}  {'':<9}{'':>9}{'':>8}{'':>7}{'':>6}{'':>6}{row.seconds:>7.1f}  ERROR {row.error}"
    chapters = f"{len(row.chapters_found)}/{len(row.chapters_found) + len(row.chapters_missing)}"
    toc = f"{row.business_toc_matched}/{row.business_toc_entries}"
    notes = []
    if row.business_sections_source != "toc":
        notes.append(f"sections from {row.business_sections_source.replace('_', ' ')}")
    if row.chapters_missing:
        notes.append("missing: " + ", ".join(row.chapters_missing))
    if row.chapters_duplicated:
        notes.append("duplicated: " + ", ".join(row.chapters_duplicated))
    return (
        f"{head}{row.pages:>6}{row.pages_printed:>8}  {chapters:<9}{row.business_sections:>9}{toc:>8}"
        f"{row.notes:>7}{row.statements:>6}{row.warnings:>6}{row.seconds:>7.1f}  {'; '.join(notes)}"
    ).rstrip()


@app.command("parse-check")
def parse_check(
    ticker: Annotated[str | None, typer.Argument(help="Only this ticker")] = None,
    fiscal_year: Annotated[int | None, typer.Argument(help="Only this fiscal year")] = None,
) -> None:
    """Parse every stored report (or the ones named) and print a coverage row per report.

    Stored data only: no provider calls. Exits 1 if any report fails to parse.
    """
    from stock_analyzer.services import scorecard

    try:
        rows = scorecard.scorecard(_ctx("cached"), ticker, fiscal_year)
    except (AnalyzerError, MissingCredential, ValueError) as exc:
        _fail(exc)
        return
    if not rows:
        typer.echo("no stored reports")
        return
    typer.echo(SCORE_HEADER)
    for row in rows:
        line = render_score_row(row)
        if row.error:
            typer.secho(line, fg=typer.colors.RED)
        else:
            typer.echo(line)
    if any(r.error for r in rows):
        raise typer.Exit(1)


def _fmt_decimal(raw: str | None) -> str:
    if raw is None:
        return "—"
    from decimal import Decimal

    d = Decimal(raw)
    return f"{d:,.0f}" if d == d.to_integral_value() or abs(d) >= 1000 else f"{d:,}"


@app.command("fin-raw")
def fin_raw(
    ticker: str,
    mode: ModeOpt = "cached",
    as_of: Annotated[
        str | None, typer.Option("--as-of", help="Only values available by this date (YYYY-MM-DD)")
    ] = None,
) -> None:
    """Print a company's normalized financial values, grouped by statement and fiscal year."""
    from datetime import date

    from stock_analyzer.services import financials as fin_service

    try:
        cutoff = date.fromisoformat(as_of) if as_of else None
        out = fin_service.financials(_ctx(mode), ticker, as_of=cutoff)
    except (AnalyzerError, MissingCredential, ValueError) as exc:
        _fail(exc)
        return
    years = [str(y) for y in out.years]
    width = max((len(i.label) for s in out.statements for i in s.items), default=10) + 2
    typer.echo(f"{out.ticker} — currency {out.currency}" + (f", as of {out.as_of}" if out.as_of else ""))
    for st in out.statements:
        typer.echo("")
        typer.echo(f"{st.label} ({st.statement})")
        typer.echo(f"{'':{width}}" + "".join(f"{('FY' + y):>18}" for y in years))
        for it in st.items:
            label = ("  " * it.depth + it.label)[: width - 1]
            typer.echo(f"{label:{width}}" + "".join(f"{_fmt_decimal(it.values.get(y)):>18}" for y in years))


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
