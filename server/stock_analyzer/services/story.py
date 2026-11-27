"""Story service: the saved story, and live story runs (company-story spec, design D12).

The API router and the CLI ``story`` command both call these functions.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from stock_analyzer.agents_model import FakeAgentModels, agent_model_factory
from stock_analyzer.errors import LiveModeDisabled
from stock_analyzer.services.companies import resolve_company
from stock_analyzer.services.context import Ctx
from stock_analyzer.story.agents import ModelFactory
from stock_analyzer.story.pipeline import (
    PreparedStory,
    StoryEvent,
    StoryRun,
    latest_run,
    prepare_story,
    stream_story,
)


def latest(ctx: Ctx, ticker: str) -> StoryRun:
    """The latest saved story run; no LLM or provider call. ``NotCached`` when there is none."""
    company = resolve_company(ctx, ticker)
    return latest_run(ctx.store, company.ticker)


def resolve_models(ctx: Ctx, override: ModelFactory | None = None) -> ModelFactory:
    """The agent model factory for a story run. Paid runs need live mode: cached mode spends nothing."""
    if override is not None:
        return override
    factory = agent_model_factory(ctx.settings, store=ctx.store)
    if not isinstance(factory, FakeAgentModels) and ctx.mode != "live":
        raise LiveModeDisabled(
            "a story run calls the LLM, which costs money: switch to live mode (or run with LLM_FAKE=true)"
        )
    return factory


def prepare(ctx: Ctx, ticker: str, *, as_of: date | None = None) -> PreparedStory:
    """Report selection, comparison, facts and the token budget: every input error, no LLM call."""
    return prepare_story(ctx, ticker, as_of=as_of)


def run(prep: PreparedStory, models: ModelFactory) -> Iterator[StoryEvent]:
    """Progress events, then ``done`` with the saved run or ``error``."""
    return stream_story(prep, models)
