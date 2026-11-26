"""Story endpoints: the saved story (cached) and a streamed live story run (design D12)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from stock_analyzer.api.deps import CtxDep
from stock_analyzer.api.errors import to_error
from stock_analyzer.api.schemas import StoryEvents, StoryProgress, StoryRequest
from stock_analyzer.api.sse import sse_event
from stock_analyzer.services import story
from stock_analyzer.services.context import Ctx
from stock_analyzer.story.pipeline import StoryRun

router = APIRouter(prefix="/api/companies", tags=["story"])


@router.get(
    "/{ticker}/story",
    response_model=StoryRun,
    summary="The latest saved company story (no LLM or provider call)",
)
def get_story(ctx: CtxDep, ticker: str) -> StoryRun:
    return story.latest(ctx, ticker)


@router.post(
    "/{ticker}/story",
    summary="Generate a company story (live mode; streamed progress, then the saved run)",
    response_class=EventSourceResponse,
    responses={
        200: {
            "model": StoryEvents,
            "description": "text/event-stream of `progress` events, then one `done` (the saved StoryRun) "
            "or `error` event.",
        }
    },
)
def run_story(request: Request, ticker: str, body: StoryRequest) -> EventSourceResponse:
    ctx = Ctx(request.app.state.settings, mode=body.mode)  # type: ignore[arg-type]
    # mode, report and budget checks happen before the stream starts (plain JSON errors)
    try:
        models = story.resolve_models(ctx, getattr(request.app.state, "agent_models", None))
        prepared = story.prepare(ctx, ticker, as_of=body.as_of)
    except Exception:
        ctx.close()
        raise

    def events() -> Iterator[dict[str, str]]:
        try:
            for event in story.run(prepared, models):
                if event.type == "progress":
                    yield sse_event(
                        "progress", StoryProgress(step=event.step, message=event.message, data=event.data)
                    )
                elif event.type == "done":
                    yield sse_event("done", event.data)
                else:
                    yield sse_event("error", to_error(event.data))
        except Exception as exc:  # report the failure in-band; the HTTP status is already 200
            yield sse_event("error", to_error(exc))
        finally:
            ctx.close()

    return EventSourceResponse(events(), ping=15)
