"""API-only schemas (most responses reuse ``services.models`` directly)."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from stock_analyzer.api.errors import ErrorOut
from stock_analyzer.osint.models import OsintProgress, ResearchResult


class StorageHealth(BaseModel):
    backend: Literal["fs", "postgres"]
    ok: bool = Field(
        description="The state store is reachable and ready (connection details are never shown)"
    )


class HealthOut(BaseModel):
    status: str = "ok"
    version: str
    allow_live: bool
    llm_fake: bool
    credentials: dict[str, bool]  # whether each credential is configured; values are never returned
    models: dict[str, str]
    storage: StorageHealth


class PageRange(BaseModel):
    first: int = Field(ge=1)
    last: int = Field(ge=1)


class PlaygroundRequest(BaseModel):
    ticker: str
    fiscal_year: int
    question: str = Field(min_length=1, max_length=2000)
    node_id: str | None = None
    pages: PageRange | None = None
    mode: str = Field(default="cached", pattern="^(cached|live)$")

    @model_validator(mode="after")
    def _one_selection(self) -> PlaygroundRequest:
        if (self.node_id is None) == (self.pages is None):
            raise ValueError("select exactly one of node_id or pages")
        return self


class PlaygroundUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    cost: float | None


class PlaygroundDelta(BaseModel):
    text: str


class PlaygroundDone(BaseModel):
    model: str
    usage: PlaygroundUsage
    latency_ms: int
    paragraph_ids: list[str]


class PlaygroundEvents(BaseModel):
    """Documentation of the server-sent events: ``event: delta|done|error`` with these JSON payloads."""

    delta: PlaygroundDelta
    done: PlaygroundDone
    error: ErrorOut


class StoryRequest(BaseModel):
    mode: str = Field(default="live", pattern="^(cached|live)$")
    as_of: date | None = Field(
        default=None, description="Use only reports published by this date (default: today)"
    )


class StoryProgress(BaseModel):
    step: str = Field(
        description="reports, budget, agent_start, agent_done, agent_failed, tool, verify or saved"
    )
    message: str
    data: dict[str, Any] | None = None


class StoryEvents(BaseModel):
    """Documentation of the server-sent events: ``event: progress|done|error`` with these JSON payloads.
    ``done`` carries the saved story run (see ``StoryRun``)."""

    progress: StoryProgress
    done: dict[str, Any]
    error: ErrorOut


class OsintRunIn(BaseModel):
    """Body of a live OSINT research run. ``months`` defaults to the server's window (36)."""

    months: int | None = Field(default=None, ge=1, le=120)


class OsintEvents(BaseModel):
    """Documentation of the OSINT run stream: ``event: progress|done|error`` with these JSON payloads."""

    progress: OsintProgress
    done: ResearchResult
    error: ErrorOut
