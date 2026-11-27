"""Command-line interface (typer). Thin adapter over ``services`` (design D4).

Commands: fetch, usage, structure, parse-check, fin-raw, ratios, compare, story, osint, peer-benchmark, peer-financials, market-research,
companies list|add|remove, db init.
"""

from __future__ import annotations

import json
import sys
from contextlib import closing
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


@app.command("peer-benchmark")
def peer_benchmark_cmd(
    ticker: str,
    run: Annotated[bool, typer.Option("--run", help="Live: estimate credits for missing data")] = False,
    confirm: Annotated[bool, typer.Option("--confirm", help="With --run: fetch after estimating")] = False,
    max_fetch: Annotated[int, typer.Option(min=1, max=12, help="Most financials requests per run")] = 5,
) -> None:
    """Print ratios beside curated or same-ISIC peers per market (stored data unless --run)."""
    from stock_analyzer.services import peer_benchmark as pb

    try:
        with closing(_ctx("live" if run else "cached")) as ctx:
            if run:
                result = pb.live_run(ctx, ticker, pb.PeerBenchmarkRunIn(confirm=confirm, max_fetch=max_fetch))
            else:
                result = pb.benchmark(ctx, ticker)
    except (AnalyzerError, MissingCredential, ValueError) as exc:
        _fail(exc)
        return
    typer.echo(result.model_dump_json(indent=2))


@app.command("peer-financials")
def peer_financials_cmd(
    ticker: str,
    limit: Annotated[int, typer.Option(min=1, help="Maximum number of peers")] = 5,
    peer_country: Annotated[
        list[str] | None, typer.Option("--peer-country", help="Additional country code (repeatable)")
    ] = None,
    mode: ModeOpt = "cached",
) -> None:
    """Print annual statements for listed peers in Israel, optionally filling from named markets."""
    from stock_analyzer.services.peers import peer_financials

    try:
        with closing(_ctx(mode)) as ctx:
            result = peer_financials(ctx, ticker, limit, peer_country or [])
    except (AnalyzerError, MissingCredential, ValueError) as exc:
        _fail(exc)
        return
    typer.echo(result.model_dump_json(indent=2))


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
        typer.echo(
            f"schema {store.schema!r} was already present; applied again to add any new tables, existing data kept"
        )
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


def _fmt_ratio(raw: str | None, unit: str) -> str:
    if raw is None:
        return "—"
    from decimal import Decimal

    d = Decimal(raw)
    if unit == "percent":
        return f"{d * 100:.2f}%"
    if unit == "amount":
        return f"{d:,.0f}"
    return f"{d:.2f}"


@app.command("ratios")
def ratios_cmd(
    ticker: str,
    mode: ModeOpt = "cached",
    as_of: Annotated[
        str | None, typer.Option("--as-of", help="Only values available by this date (YYYY-MM-DD)")
    ] = None,
) -> None:
    """Print a company's financial ratios by group and fiscal year (* = low confidence)."""
    from datetime import date

    from stock_analyzer.services import ratios as ratio_service

    try:
        cutoff = date.fromisoformat(as_of) if as_of else None
        out = ratio_service.ratios(_ctx(mode), ticker, as_of=cutoff)
    except (AnalyzerError, MissingCredential, ValueError) as exc:
        _fail(exc)
        return
    years = [str(y) for y in out.years]
    width = max((len(r.name_he) for g in out.groups for r in g.ratios), default=10) + 2
    typer.echo(
        f"{out.ticker} — template {out.template}, currency {out.currency}"
        + (f", as of {out.as_of}" if out.as_of else "")
    )
    for group in out.groups:
        typer.echo("")
        typer.echo(f"{group.label} ({group.group})")
        typer.echo(f"{'':{width}}" + "".join(f"{('FY' + y):>16}" for y in years))
        for r in group.ratios:
            cells = []
            for y in years:
                v = r.values[y]
                mark = "*" if v.value is not None and v.confidence == "low" else " "
                cells.append(f"{_fmt_ratio(v.value, r.unit) + mark:>16}")
            typer.echo(f"{r.name_he:{width}}" + "".join(cells))
    failed = {y: [c.id for c in out.checks[y] if c.status == "failed"] for y in years}
    typer.echo("")
    typer.echo(
        "* low confidence. Failed checks: "
        + ("; ".join(f"FY{y} {', '.join(ids)}" for y, ids in failed.items() if ids) or "none")
    )


TREND_ARROWS = {"improving": "up", "stable": "flat", "deteriorating": "down", "unclear": "?"}


def render_osint(result) -> list[str]:
    """Text view of an OSINT result: profile, key drivers, areas by importance, risks, strengths, sources."""
    from stock_analyzer.osint.models import AREA_INFO

    card = result.scorecard
    lines = [
        f"{result.ticker} — {result.company_name}",
        f"window {result.window_start} to {result.run_date} ({result.window_months} months), model {result.model}"
        + (" [stored result]" if result.from_cache else ""),
    ]
    if result.profile:
        p = result.profile
        lines.append(f"industry: {p.industry}" + (f" · regulator: {p.regulator}" if p.regulator else ""))
        if p.business_lines:
            lines.append(f"business lines: {', '.join(p.business_lines)}")
        if p.controlling_shareholder:
            lines.append(f"controlling shareholder: {p.controlling_shareholder}")
    lines += [
        "",
        f"Overall: {card.overall_label.upper()} (trend {TREND_ARROWS[card.overall_trend]}: {card.overall_trend})",
        f"  {card.overall_rationale}",
    ]
    if card.overall_trend_reason:
        lines.append(f"  {card.overall_trend_reason}")
    if card.key_drivers:
        lines += ["", "Key drivers:"]
        for d in card.key_drivers:
            ids = f" [{', '.join(d.finding_ids)}]" if d.finding_ids else ""
            lines.append(f"  {d.driver}: {d.status}{ids}")
            if d.explanation:
                lines.append(f"    {d.explanation}")
    lines += ["", "Areas:"]
    rank = {"high": 0, "medium": 1, "low": 2}
    for a in sorted(card.areas, key=lambda a: rank[a.importance]):
        ids = f" [{', '.join(a.finding_ids)}]" if a.finding_ids else ""
        lines.append(
            f"  {a.area} ({AREA_INFO[a.area][0]}): {a.label} · importance {a.importance} · "
            f"trend {TREND_ARROWS[a.trend]}{ids}"
        )
        if a.assessment:
            lines.append(f"    {a.assessment}")
        if a.trend_reason:
            lines.append(f"    trend: {a.trend_reason}")
    for title, points in (("Risks", card.risks), ("Strengths", card.strengths)):
        lines += ["", f"{title}:"]
        lines += [f"  {i}. {p.text} [{', '.join(p.finding_ids)}]" for i, p in enumerate(points, 1)] or [
            "  none"
        ]
    lines += ["", "Summary:", f"  {card.summary_he}", "", "Sources:"]
    for f in result.findings:
        tags = [f.area, *f.also_areas, f.signal, f.published_at or "undated", f.verdict] + (
            ["filing-derived"] if f.derived_from_filing else []
        )
        lines.append(f"  {f.id} [{', '.join(tags)}] {f.claim}")
        lines.append(f"      {f.source_url}")
        for other in f.also_sources:
            lines.append(f"      also: {other.url}")
    d = result.dropped
    cost = f"${result.cost_usd:.4f}" if result.cost_usd is not None else "unknown"
    lines += [
        "",
        f"searches {result.searches_used}/{result.search_limit} · dropped: blocked {d.get('blocked', 0)}, "
        f"not from a search {d.get('not_searched', 0)}, outside window {d.get('outside_window', 0)}, "
        f"not supported by source {d.get('unsupported', 0)} · duplicates merged {result.merged} · cost {cost}",
    ]
    return lines


@app.command("osint")
def osint_cmd(
    ticker: str,
    months: Annotated[
        int | None, typer.Option("--months", help="Research window in months (default 36)")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the full result as JSON")] = False,
    mode: Annotated[
        str | None, typer.Option("--mode", help="live or cached (default: live unless ALLOW_LIVE=false)")
    ] = None,
) -> None:
    """OSINT stability research from open sources (never the official filings).

    Live mode always searches the web afresh and costs OpenRouter credit; cached mode (or ALLOW_LIVE=false)
    prints the latest stored result.
    """
    from stock_analyzer.osint.agents import NoFindings
    from stock_analyzer.services import osint

    if hasattr(sys.stdout, "reconfigure"):  # model text can hold characters the console code page lacks
        sys.stdout.reconfigure(errors="replace")
    settings = get_settings()
    try:
        ctx = Ctx(settings, mode=mode or ("live" if settings.allow_live else "cached"))  # type: ignore[arg-type]
        result = osint.run_research(ctx, ticker, months)
    except (AnalyzerError, MissingCredential, NoFindings, ValueError) as exc:
        _fail(exc)
        return
    if as_json:
        json.dump(result.model_dump(mode="json"), sys.stdout, ensure_ascii=False, indent=2)
        typer.echo()
        return
    for line in render_osint(result):
        typer.echo(line)


@app.command("market-research")
def market_research_cmd(
    ticker: str,
    market: Annotated[
        list[str] | None, typer.Option("--market", help="IL, EUROPE, or US (repeatable)")
    ] = None,
    months: Annotated[int | None, typer.Option("--months", min=1, help="Research window in months")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the full brief as JSON")] = False,
    mode: ModeOpt = "cached",
) -> None:
    """Research a tracked company's industry across Israel, Europe and the United States."""
    from stock_analyzer.llm import LLMError
    from stock_analyzer.osint.market import MARKET_NAMES
    from stock_analyzer.services.market_research import run_market_research

    try:
        with closing(_ctx(mode)) as ctx:
            result = run_market_research(ctx, ticker, markets=market, months=months)
    except (AnalyzerError, LLMError, MissingCredential, ValueError) as exc:
        _fail(exc)
        return
    if as_json:
        typer.echo(result.model_dump_json(indent=2))
        return

    industry = result.industry
    name = f" ({industry.name})" if industry.name else ""
    typer.echo(
        f"{result.ticker} | ISIC Rev. 5 {industry.code}{name} | {result.window_start} to {result.run_date}"
    )
    for brief in result.markets:
        typer.echo(f"\n{MARKET_NAMES[brief.market]}")
        for section in brief.sections:
            typer.echo(section.topic.replace("_", " ").capitalize())
            if section.evidence_gap:
                typer.echo("  Insufficient evidence")
            for finding in section.findings:
                typer.echo(f"  - {finding.claim} [{finding.geography}, {finding.scope}]")
                details = [finding.classification, finding.coverage, finding.period, finding.unit]
                if metadata := " | ".join(detail for detail in details if detail):
                    typer.echo(f"    {metadata}")
                for url in finding.source_urls:
                    typer.echo(f"    {url}")


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
            lines.append(_sources_line(p))
    lines += ["", "== הסיפור מול המספרים"]
    for f in run.rendered.story_vs_numbers:
        first, *rest = _segments_text(f.segments)
        lines += [f"[{LABELS_HE[f.label]}] {first}", *rest, _sources_line(f)]
    if run.rendered.unchanged_sections:
        lines += ["", "ללא שינוי בשלוש השנים: " + ", ".join(u.title for u in run.rendered.unchanged_sections)]
    lines += ["", "== ציטוטים"]
    for pid, c in sorted(run.citations.items()):
        page = f"עמ' {c.page_printed}" if c.page_printed is not None else f"עמוד {c.page_index} בקובץ"
        lines.append(f"[{pid}] FY{c.fiscal_year} {page}")
    if run.web_sources:
        lines += ["", "== מקורות רשת"]
        for sid, src in sorted(run.web_sources.items()):
            date_text = src.published_at or "תאריך לא ידוע"
            lines.append(f"[{sid}] {src.title} ({date_text}) {src.url}")
    return lines


def _sources_line(item) -> str:
    """Report paragraphs, then web sources marked as such."""
    parts = list(item.paragraph_ids) + [f"רשת {sid}" for sid in getattr(item, "source_ids", [])]
    return "   מקורות: " + ", ".join(parts)


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
