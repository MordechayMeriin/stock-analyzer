from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from stock_analyzer.api.errors import to_error
from stock_analyzer.api.schemas import (
    PlaygroundDelta,
    PlaygroundDone,
    PlaygroundEvents,
    PlaygroundRequest,
    PlaygroundUsage,
)
from stock_analyzer.api.sse import sse_event
from stock_analyzer.llm import DeltaEvent, DoneEvent
from stock_analyzer.services import playground
from stock_analyzer.services.context import Ctx

router = APIRouter(prefix="/api", tags=["playground"])


@router.post(
    "/playground",
    summary="Ask the main LLM about a report section (streamed)",
    response_class=EventSourceResponse,
    responses={
        200: {
            "model": PlaygroundEvents,
            "description": "text/event-stream of `delta` events, then one `done` (or `error`) event. "
            "Payload schemas are listed in PlaygroundEvents.",
        }
    },
)
def ask(request: Request, body: PlaygroundRequest) -> EventSourceResponse:
    ctx = Ctx(request.app.state.settings, mode=body.mode)  # type: ignore[arg-type]
    pages = (body.pages.first, body.pages.last) if body.pages else None
    # validation, size check and mode checks happen before the stream starts (plain JSON errors)
    try:
        prepared = playground.prepare(
            ctx, body.ticker, body.fiscal_year, body.question, node_id=body.node_id, pages=pages
        )
        llm = playground.resolve_llm(ctx, getattr(request.app.state, "llm", None))
    except Exception:
        ctx.close()
        raise

    def events() -> Iterator[dict[str, str]]:
        try:
            for event in playground.stream(llm, prepared):
                if isinstance(event, DeltaEvent):
                    yield sse_event("delta", PlaygroundDelta(text=event.text))
                elif isinstance(event, DoneEvent):
                    yield sse_event(
                        "done",
                        PlaygroundDone(
                            model=event.model,
                            usage=PlaygroundUsage(**event.usage.model_dump()),
                            latency_ms=event.latency_ms,
                            paragraph_ids=[p.pid for p in prepared.paragraphs],
                            citations=playground.citations(prepared),
                        ),
                    )
        except Exception as exc:  # report the failure in-band; the HTTP status is already 200
            yield sse_event("error", to_error(exc))
        finally:
            ctx.close()

    return EventSourceResponse(events(), ping=15)
