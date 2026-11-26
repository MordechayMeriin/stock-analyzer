"""Command-line interface (typer). Thin adapter over ``services`` (design D4).

Commands: fetch, usage, structure, fin-raw, ratios, compare, story, db init.
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
        typer.echo(
            f"schema {store.schema!r} was already present; applied again to add any new tables, existing data kept"
        )
    else:
        typer.echo(f"created schema {store.schema!r}: kv_cache, reports, financials_snapshots, usage_log")


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


def _fmt_ratio(raw: str | None, unit: str) -> str:
    if raw is None:
        return "—"
    from decimal import Decimal

    d = Decimal(raw)
    if unit in ("percent", "pp"):
        return f"{d * 100:.2f}" + ("%" if unit == "percent" else "pp")
    if unit == "money":
        return f"{d / 1_000_000:,.1f}M"
    return f"{d:.2f}"


def render_ratios(out) -> list[str]:
    """Text lines for :class:`RatiosOut`; shared by the CLI and the CLI/API parity test."""
    years = sorted(out.years)
    by = {(r.code, r.fiscal_year): r for r in out.ratios}
    codes = list(dict.fromkeys(r.code for r in out.ratios))
    lines = [
        f"{out.ticker} — core ratios, currency {out.currency}" + (f", as of {out.as_of}" if out.as_of else "")
    ]
    lines.append(f"{'':28}" + "".join(f"{'FY' + str(y):>14}" for y in years))
    for code in codes:
        cells = []
        for y in years:
            r = by.get((code, y))
            cell = _fmt_ratio(r.value, r.unit) if r else "—"
            cells.append(f"{cell + (' *' if r and r.confidence == 'low' else '  '):>14}")
        lines.append(f"{code:28}" + "".join(cells))
    lines.append("* low confidence: an input is in a failed data-quality check")
    if len(years) >= 2:
        y0, y1 = years[-2], years[-1]
        lines.append("")
        lines.append(f"changes FY{y0} → FY{y1}")
        for c in out.changes:
            if (c.from_year, c.to_year) == (y0, y1):
                note = f"  ({c.reason})" if c.reason else ""
                low = f"  * {', '.join(c.failed_checks)}" if c.confidence == "low" else ""
                lines.append(f"  {c.code:26}{_fmt_ratio(c.value, c.unit):>12}{low}{note}")
    failed = [ch for ch in out.checks if ch.status == "fail"]
    lines.append("")
    lines.append("failed checks" if failed else "no failed checks")
    for ch in failed:
        lines.append(
            f"  FY{ch.fiscal_year} {ch.check_id}: {ch.description_he} — "
            f"expected {_fmt_decimal(ch.expected)}, actual {_fmt_decimal(ch.actual)} (tolerance {ch.tolerance})"
        )
    not_run = sorted(
        {f"{ch.check_id}" for ch in out.checks if ch.status == "not_run" and ch.fiscal_year == years[-1]}
    )
    if not_run:
        lines.append(f"  not run for FY{years[-1]} (missing inputs): {', '.join(not_run)}")
    return lines


@app.command()
def ratios(
    ticker: str,
    mode: ModeOpt = "cached",
    as_of: Annotated[
        str | None, typer.Option("--as-of", help="Only values available by this date (YYYY-MM-DD)")
    ] = None,
) -> None:
    """Print core ratios per fiscal year with changes, confidence and failed data-quality checks."""
    from datetime import date

    from stock_analyzer.services import analysis

    try:
        cutoff = date.fromisoformat(as_of) if as_of else None
        out = analysis.ratios(_ctx(mode), ticker, as_of=cutoff)
    except (AnalyzerError, MissingCredential, ValueError) as exc:
        _fail(exc)
        return
    for line in render_ratios(out):
        typer.echo(line)


def render_comparison(out) -> list[str]:
    """Text lines for a :class:`Comparison`; shared by the CLI and the CLI/API parity test."""
    pairs = [f"FY{a}→{b % 100:02d}" for a, b in zip(out.years, out.years[1:], strict=False)]
    lines = [
        f"{out.ticker} — business sections FY{out.years[0]}–FY{out.years[-1]} "
        f"(unchanged at similarity ≥ {out.unchanged_threshold})",
        f"{'':52}" + "".join(f"{p:>20}" for p in pairs),
    ]
    for s in out.sections:
        indent = "  " if s.level == 3 else ""
        title = (indent + s.title)[:50]
        cells = []
        for a, b in zip(out.years, out.years[1:], strict=False):
            pair = next((p for p in s.pairs if (p.from_year, p.to_year) == (a, b)), None)
            if pair is None:
                cells.append(f"{'':>20}")
            else:
                score = f" {pair.similarity:.2f}" if pair.similarity is not None else ""
                cells.append(f"{pair.status + score:>20}")
        ids = " ".join(f"{y}:{n}" for y, n in s.node_ids.items())
        lines.append(f"{title:52}" + "".join(cells) + f"   {ids}")
    return lines


@app.command("compare")
def compare_cmd(
    ticker: str,
    years: Annotated[list[int], typer.Argument(help="Fiscal years to compare, e.g. 2023 2024 2025")],
    mode: ModeOpt = "cached",
) -> None:
    """Align a company's business-description sections across fiscal years and show what changed."""
    from stock_analyzer.services import compare as compare_service

    try:
        out = compare_service.compare(_ctx(mode), ticker, years)
    except (AnalyzerError, MissingCredential, ValueError) as exc:
        _fail(exc)
        return
    for line in render_comparison(out):
        typer.echo(line)


LABELS_HE = {"consistent": "עקבי", "tension": "מתח", "unexplained": "לא מוסבר"}


def _segments_text(segments) -> list[str]:
    body = "".join(s.text if s.type == "text" else s.display for s in segments if s.type != "caveat")
    caveats = [f"  ⚠ {s.text}" for s in segments if s.type == "caveat"]
    return [body, *caveats]


def render_story(run) -> list[str]:
    """Text lines for a :class:`StoryRun`; shared by the CLI and the CLI/API parity test."""
    years = f"FY{run.years[0]}–FY{run.years[-1]}"
    lines = [
        f"{run.ticker} — story {years} (as of {run.as_of}, run {run.run_id[:8]}, ${run.usage.cost_usd:.2f})"
    ]
    sections = (("מה החברה עושה", run.rendered.what_it_does), ("מה השתנה", run.rendered.what_changed))
    for title, paragraphs in sections:
        lines += ["", f"== {title}"]
        for p in paragraphs:
            lines += _segments_text(p.segments)
            lines.append("   מקורות: " + ", ".join(p.paragraph_ids))
    lines += ["", "== הסיפור מול המספרים"]
    for f in run.rendered.story_vs_numbers:
        first, *rest = _segments_text(f.segments)
        lines += [f"[{LABELS_HE[f.label]}] {first}", *rest, "   מקורות: " + ", ".join(f.paragraph_ids)]
    if run.rendered.unchanged_sections:
        lines += ["", "ללא שינוי בשלוש השנים: " + ", ".join(u.title for u in run.rendered.unchanged_sections)]
    lines += ["", "== ציטוטים"]
    for pid, c in sorted(run.citations.items()):
        page = f"עמ' {c.page_printed}" if c.page_printed is not None else f"עמוד {c.page_index} בקובץ"
        lines.append(f"[{pid}] FY{c.fiscal_year} {page}  {c.url or ''}".rstrip())
    return lines


@app.command()
def story(
    ticker: str,
    live: Annotated[
        bool, typer.Option("--live", help="Generate a new story (calls the LLM, costs money)")
    ] = False,
    as_of: Annotated[
        str | None, typer.Option("--as-of", help="Use only reports published by this date (YYYY-MM-DD)")
    ] = None,
) -> None:
    """Print the latest saved company story, or generate a new one with --live."""
    from datetime import date

    from stock_analyzer.services import story as story_service

    if not live:
        try:
            run = story_service.latest(_ctx("cached"), ticker)
        except (AnalyzerError, MissingCredential, ValueError) as exc:
            _fail(exc)
            return
        for line in render_story(run):
            typer.echo(line)
        return
    ctx = _ctx("live")
    try:
        cutoff = date.fromisoformat(as_of) if as_of else None
        models = story_service.resolve_models(ctx)
        prepared = story_service.prepare(ctx, ticker, as_of=cutoff)
        run = None
        for event in story_service.run(prepared, models):
            if event.type == "progress":
                typer.echo(f"· {event.message}", err=True)
            elif event.type == "done":
                run = event.data
            else:
                raise event.data
    except Exception as exc:  # noqa: BLE001  (reported with its code, like every command)
        _fail(exc)
        return
    finally:
        ctx.close()
    for line in render_story(run):
        typer.echo(line)


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
