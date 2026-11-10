"""API-only schemas (most responses reuse ``services.models`` directly)."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from stock_analyzer.api.errors import ErrorOut


class HealthOut(BaseModel):
    status: str = "ok"
    version: str
    allow_live: bool
    llm_fake: bool
    credentials: dict[str, bool]  # whether each credential is configured; values are never returned
    models: dict[str, str]


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
    citations: dict[str, str | None]  # paragraph id → document_url#page=N


class PlaygroundEvents(BaseModel):
    """Documentation of the server-sent events: ``event: delta|done|error`` with these JSON payloads."""

    delta: PlaygroundDelta
    done: PlaygroundDone
    error: ErrorOut
