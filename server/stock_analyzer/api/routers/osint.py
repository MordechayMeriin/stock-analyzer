"""OSINT stability research over HTTP (add-osint-web design D1-D6).

``GET`` serves the latest stored result and never calls a provider. ``POST`` runs fresh research in live
mode and streams ``progress`` events, then one ``done`` (the full result) or ``error`` event. The run works
in its own thread with its own context, so a client that disconnects does not stop it: the result is still
stored and served by the next ``GET``.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Body, Query, Request
from sse_starlette.sse import EventSourceResponse

from stock_analyzer.api.deps import CtxDep
from stock_analyzer.api.errors import to_error
from stock_analyzer.api.schemas import OsintEvents, OsintRunIn
from stock_analyzer.api.sse import sse_event
from stock_analyzer.osint.models import ResearchResult
from stock_analyzer.services import osint
from stock_analyzer.services.context import Ctx

router = APIRouter(prefix="/api/companies", tags=["osint"])

MonthsParam = Annotated[
    int | None, Query(ge=1, le=120, description="Research window in months (default: the server's, 36)")
]


@router.get(
    "/{ticker}/osint",
    response_model=ResearchResult,
    summary="Latest stored OSINT stability research (never calls a provider)",
    description="Open-source stability research, never based on official filings. Returns the latest stored "
    "result for the ticker and window in either mode; `not_cached` (409) when none is stored.",
)
def get_osint(ctx: CtxDep, ticker: str, months: MonthsParam = None) -> ResearchResult:
    return osint.stored_result(ctx, ticker, months)


@router.post(
    "/{ticker}/osint",
    summary="Run fresh OSINT stability research (live mode, streamed)",
    description="Searches the web afresh and costs OpenRouter credit (about $1); takes several minutes. "
    "Refused before the stream starts with `live_required` (cached mode), `live_disabled` (cached-only "
    "server), `missing_credential`, `company_not_found`, or `research_in_progress` (a run for this ticker "
    "and window is already running in this server process). The run continues if the client disconnects.",
    response_class=EventSourceResponse,
    responses={
        200: {
            "model": OsintEvents,
            "description": "text/event-stream of `progress` events, then one `done` (or `error`) event. "
            "Payload schemas are listed in OsintEvents.",
        }
    },
)
def run_osint(
    request: Request,
    ctx: CtxDep,
    ticker: str,
    body: Annotated[OsintRunIn | None, Body()] = None,
) -> EventSourceResponse:
    ticker, months = osint.check_can_run(ctx, ticker, body.months if body else None)
    osint.acquire_run(ticker, months)
    settings, mode = request.app.state.settings, ctx.mode
    events: queue.Queue[tuple[str, Any]] = queue.Queue()

    def work() -> None:
        try:
            run_ctx = Ctx(settings, mode=mode)
            try:
                result = osint.run_research(
                    run_ctx, ticker, months, on_progress=lambda p: events.put(("progress", p))
                )
            finally:
                run_ctx.close()
            events.put(("done", result))
        except Exception as exc:  # reported in-band; the HTTP status is already 200
            events.put(("error", to_error(exc)))
        finally:
            osint.release_run(ticker, months)

    try:
        threading.Thread(target=work, name=f"osint-{ticker}-{months}m", daemon=True).start()
    except Exception:
        osint.release_run(ticker, months)
        raise

    def stream() -> Iterator[dict[str, str]]:
        while True:
            event, payload = events.get()
            yield sse_event(event, payload)
            if event != "progress":
                return

    return EventSourceResponse(stream(), ping=15)
