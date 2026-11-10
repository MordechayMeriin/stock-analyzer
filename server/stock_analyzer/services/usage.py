"""Usage service: provider credits plus LLM spend from the logs."""

from __future__ import annotations

from stock_analyzer.errors import AnalyzerError
from stock_analyzer.ingest.fr_client import read_fr_totals
from stock_analyzer.llm import read_llm_totals
from stock_analyzer.services.context import Ctx
from stock_analyzer.services.models import UsageOut


def usage(ctx: Ctx) -> UsageOut:
    provider, error = None, None
    try:
        provider = ctx.fr.usage()
    except AnalyzerError as exc:
        error = exc.message
    except Exception as exc:  # missing key etc.: the panel still shows local totals
        error = str(exc)
    return UsageOut(
        provider=provider,
        provider_error=error,
        fr_log=read_fr_totals(ctx.settings.logs_dir / "fr.jsonl"),
        llm=read_llm_totals(ctx.settings.logs_dir / "llm.jsonl"),
    )
