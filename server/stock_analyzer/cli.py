"""Command-line interface (typer). Thin adapter over ``services`` (design D4).

Commands: fetch, usage, structure, fin-raw.
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
    c = out.coverage
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
        f"{c['business_sections_matched_from_toc']}), subsections: {c['subsections']}"
    )
    typer.echo(
        f"directors' headings: {c['directors_headings']}, auditor's reports: {c['auditor_reports']}, "
        f"statements: {c['statements']}, notes: {c['notes']}"
        + (f" (no heading for {c['note_numbers_missing']})" if c["note_numbers_missing"] else "")
    )
    typer.echo(f"paragraphs in chapters: {c['paragraphs_in_chapters']}/{c['paragraphs']}")
    for warning in out.warnings:
        typer.secho(f"warning: {warning}", fg=typer.colors.YELLOW)


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
