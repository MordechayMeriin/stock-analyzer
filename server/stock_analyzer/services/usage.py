"""Usage service: provider credits plus LLM spend from the usage logs in the state store."""

from __future__ import annotations

from stock_analyzer.errors import AnalyzerError
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
        fr_log=ctx.store.totals("fr"),
        llm=ctx.store.totals("llm"),
    )
