"""The company report contract (docs/company-report-spec.md) and the rater's output type.

The contract models mirror ``web/src/features/report/types.ts`` field for field, snake_case as on
the wire, with money as decimal strings. The rater output (design D2) carries fact ids, never
display strings: code renders every number from the story run's facts.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field, SerializerFunctionWrapHandler, model_serializer

Tone = Literal["positive", "negative", "neutral"]
Direction = Literal["up", "down", "flat"]
EventType = Literal[
    "report",
    "acquisition",
    "leadership",
    "guidance",
    "financing",
    "legal",
    "regulatory",
    "buyback",
    "insider",
    "other",
]
AxisId = Literal["stability", "safety", "revenue_quality", "growth", "profitability"]

SCHEMA_VERSION = "1.0"

# Axis order and Hebrew labels (company-report spec, "Five story-based axes").
AXES: tuple[tuple[AxisId, str], ...] = (
    ("stability", "יציבות"),
    ("safety", "ביטחון"),
    ("revenue_quality", "איכות הכנסות"),
    ("growth", "צמיחה"),
    ("profitability", "רווחיות"),
)

# Character limits from the contract.
MAX_AXIS_LABEL = 16
MAX_DRIVER = 28
MAX_EVENT_TITLE = 40
MAX_EVENT_SUMMARY = 80
MAX_HEADLINE = 80
MAX_DETAIL_TEXT = 600
MAX_SUMMARY = 160
MAX_FACTORS = 5


# ---------------------------------------------------------------- contract


class _Wire(BaseModel):
    """Optional fields the JSON Schema does not allow as null are left out when they are None."""

    _omit_if_none: ClassVar[tuple[str, ...]] = ()

    @model_serializer(mode="wrap")
    def _drop_empty(self, handler: SerializerFunctionWrapHandler):  # no return type: keep the field schema
        data = handler(self)
        for name in self._omit_if_none:
            if data.get(name) is None:
                data.pop(name, None)
        return data


class Trend(_Wire):
    _omit_if_none = ("delta",)
    direction: Direction
    delta: float | None = None
    tone: Tone


class Driver(_Wire):
    label: str
    tone: Tone


class Score(_Wire):
    fiscal_year: int
    value: int | None
    sector_median: float | None = None
    trend: Trend | None = None
    driver: Driver | None = None


class Axis(_Wire):
    _omit_if_none = ("detail_url",)
    id: str
    label: str
    status: Literal["ok", "insufficient_data"]
    detail_url: str | None = None
    scores: list[Score]


class Sector(_Wire):
    id: str
    name: str


class Company(_Wire):
    _omit_if_none = ("exchange",)
    ticker: str
    name_he: str
    name_en: str | None = None
    logo_url: str | None = None
    exchange: str | None = None
    currency: str
    sector: Sector


class ReportInfo(_Wire):
    type: Literal["annual"] = "annual"
    fiscal_year: int
    period_end: str
    published_at: str


class ReportEvent(_Wire):
    _omit_if_none = ("summary", "tone")
    id: str
    date: str
    date_precision: Literal["day", "month"]
    type: EventType
    title: str
    summary: str | None = None
    importance: Literal[1, 2, 3]
    tone: Tone | None = None
    source_url: str | None = None


class MetricPoint(_Wire):
    fiscal_year: int
    value: str | None


class MetricChange(_Wire):
    _omit_if_none = ("pct",)
    direction: Direction
    pct: float | None = None
    tone: Tone


class KeyMetric(_Wire):
    _omit_if_none = ("currency",)
    id: str
    label: str
    format: Literal["currency", "percent", "ratio", "count"]
    currency: str | None = None
    series: list[MetricPoint]
    change: MetricChange | None = None


class ReportWarning(_Wire):
    code: str
    message: str


class Summary(_Wire):
    text: str


class Profile(_Wire):
    axes: list[Axis]


class Factor(_Wire):
    label: str
    display: str
    tone: Tone


class SectorComparison(_Wire):
    position: Literal["above", "below", "equal"]
    median: float


class AxisDetail(_Wire):
    axis_id: str
    fiscal_year: int
    headline: str
    factors: list[Factor]
    sector_comparison: SectorComparison | None = None
    text: str


class CompanyReport(_Wire):
    _omit_if_none = ("summary", "warnings")
    schema_version: str
    generated_at: str
    mode: Literal["cached", "live"]
    company: Company
    report: ReportInfo
    summary: Summary | None = None
    years: list[int]
    profile: Profile
    events: list[ReportEvent]
    key_metrics: list[KeyMetric]
    warnings: list[ReportWarning] | None = None


class SavedReport(BaseModel):
    """What the ``report`` cache holds per story run: the report plus its axis details."""

    run_id: str
    prompt_hash: str
    report: CompanyReport
    details: list[AxisDetail]


# ---------------------------------------------------------------- rater output (design D2)


class RatedFactor(BaseModel):
    label: str = Field(description="Short Hebrew label, e.g. 'שיעור רווח תפעולי'")
    fact_id: str = Field(
        description="The fact whose value this factor shows, e.g. RATIO:operating_margin:2025"
    )
    tone: Tone


class RatedYear(BaseModel):
    fiscal_year: int
    value: int | None = Field(description="1-10, higher is better; null when the story gives no basis")
    driver_label: str | None = Field(default=None, description="Hebrew, at most 28 characters")
    driver_tone: Tone | None = None
    evidence: list[str] = Field(
        default=[], description="Fact ids from the facts table that support the score"
    )
    headline: str | None = Field(default=None, description="Hebrew, at most 80 characters")
    factors: list[RatedFactor] = Field(default=[], description="Up to 5")
    text: str | None = Field(
        default=None, description="Hebrew plain text, at most 600 characters, no markdown"
    )


class RatedAxis(BaseModel):
    axis_id: AxisId
    years: list[RatedYear]


class RatedEvent(BaseModel):
    date: str = Field(description="YYYY-MM-DD, or YYYY-MM when only the month is known")
    date_precision: Literal["day", "month"]
    type: EventType
    title: str = Field(description="Hebrew, at most 40 characters")
    summary: str | None = Field(default=None, description="Hebrew, at most 80 characters")
    importance: Literal[1, 2, 3]
    tone: Tone | None = None


class RaterOutput(BaseModel):
    summary: str = Field(description="Hebrew, at most 160 characters")
    axes: list[RatedAxis]
    events: list[RatedEvent]
