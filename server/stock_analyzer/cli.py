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


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
