"""Response models returned by services; the API serializes these directly (one contract)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator

from stock_analyzer.companies import CompanySource
from stock_analyzer.ingest.structure import Coverage


class CompanyOut(BaseModel):
    ticker: str
    name_he: str
    name_en: str | None = None
    fr_company_id: int
    isin: str | None = None
    source: CompanySource = Field(
        description="registry: data/companies.yaml; added: added at runtime (removable)"
    )


_Ticker = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z0-9.\-]{1,15}$")
]
_NameHe = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
_Isin = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z]{2}[A-Za-z0-9]{9}[0-9]$")
]


class AddCompanyIn(BaseModel):
    """A company to start tracking, usually taken from a provider search hit."""

    fr_company_id: int = Field(gt=0, description="Provider company id (from search)")
    ticker: _Ticker = Field(description="1-15 Latin letters, digits, dots or hyphens; stored upper-case")
    name_he: _NameHe
    name_en: str | None = Field(default=None, max_length=200)
    isin: _Isin | None = None

    @field_validator("name_en", "isin", mode="before")
    @classmethod
    def _blank_is_none(cls, v: Any) -> Any:
        return v.strip() or None if isinstance(v, str) else v


class CompanySearchHit(BaseModel):
    fr_company_id: int
    name: str
    ticker: str | None = None
    isin: str | None = None
    country_code: str | None = None
    tracked_ticker: str | None = None  # set when the hit is in the tracked registry


class FilingOut(BaseModel):
    filing_id: int
    title: str
    fiscal_year: int | None
    release_datetime: datetime | None
    file_extension: str | None
    file_size: int | None
    selected: bool  # the full annual report chosen for its fiscal year
    cached: bool  # its Markdown is saved locally
    processing_status: str | None = Field(
        default=None,
        description="The provider's Markdown processing status as given (COMPLETED, QUEUED, ...); null if none",
    )


class FiscalYearFilings(BaseModel):
    fiscal_year: int
    selected_filing_id: int | None
    selection_error: str | None = None
    report_cached: bool
    markdown_availability: Literal["available", "unknown", "processing", "failed"] | None = Field(
        default=None,
        description="Whether the provider has Markdown for the selected filing: available (COMPLETED), "
        "unknown (no status), processing (PENDING/QUEUED/PROCESSING) or failed (FAILED/SKIPPED). "
        "Null when no filing is selected.",
    )
    filings: list[FilingOut]


class FilingsOut(BaseModel):
    ticker: str
    years: list[FiscalYearFilings]


class FetchedReport(BaseModel):
    fiscal_year: int
    filing_id: int
    total_chars: int
    path: str


class FetchOut(BaseModel):
    ticker: str
    reports: list[FetchedReport]
    financials_saved: bool
    credits_used: int
    network_calls: int


class UsageOut(BaseModel):
    provider: dict[str, Any] | None
    provider_error: str | None = None
    fr_log: dict[str, int]
    llm: dict[str, float | int]


class NodeOut(BaseModel):
    node_id: str
    kind: str
    chapter: str
    number: str | None
    title: str
    level: int
    para_range: tuple[int, int]
    pages: tuple[int, int]
    printed_pages: tuple[int | None, int | None]
    children: list[str]
    parent: str | None


class TocEntryOut(BaseModel):
    number: str | None
    title: str
    matched_node: str | None


class StructureOut(BaseModel):
    ticker: str
    fiscal_year: int
    filing_id: int
    page_count: int
    page_style: str
    nodes: list[NodeOut]
    roots: list[str]
    toc: list[TocEntryOut]
    coverage: Coverage
    warnings: list[str]


class ParagraphOut(BaseModel):
    pid: str
    seq: int
    text: str
    page_index: int
    page_printed: int | None
    heading_level: int
    in_table: bool


class NodeParagraphsOut(BaseModel):
    ticker: str
    fiscal_year: int
    node: NodeOut
    paragraphs: list[ParagraphOut]


class PageParagraphsOut(BaseModel):
    ticker: str
    fiscal_year: int
    page_index: int
    page_printed: int | None
    node_ids: list[str]  # deepest nodes that cover this page
    paragraphs: list[ParagraphOut]


class FinItemOut(BaseModel):
    code: str
    label: str
    depth: int
    values: dict[str, str | None]  # fiscal year → exact decimal string (never a JSON float)
    as_reported: dict[str, bool]  # fiscal year → raw value and scale both reported


class FinStatementOut(BaseModel):
    statement: str
    label: str
    items: list[FinItemOut]


class FinancialsOut(BaseModel):
    ticker: str
    currency: str | None
    years: list[int]  # newest first
    as_of: str | None
    statements: list[FinStatementOut]
    available_at: dict[str, str | None]  # fiscal year → earliest availability timestamp


# -- ratios (financial-ratios spec) — every number is an exact decimal string, never a JSON float


class RatioValueOut(BaseModel):
    value: str | None  # fraction for percent units (0.104706 = 10.47%); None = missing
    missing_reason: str | None = (
        None  # missing_input:<fields> | missing_prior_input:<field> | zero_denominator | …
    )
    missing_message_he: str | None = None
    confidence: Literal["high", "low"] = "high"
    failed_checks: list[str] = []  # check ids; "<id>:<fy>" when the check failed in another year
    derived_inputs: list[str] = []  # "<field>:<fy>"
    avg_used: bool = False
    inputs: dict[str, str] = {}  # field (closing) | "opening:<field>" | "prior:<field>" → value
    delta: str | None = None  # change from the year before, in the ratio's unit (relative for amounts)
    status: Literal["improved", "deteriorated", "changed", "stable", "na"] = "na"
    notes: list[str] = []  # e.g. non_annual_source


class RatioSeriesOut(BaseModel):
    code: str
    name_he: str
    unit: Literal["percent", "ratio", "amount", "days"]
    direction: Literal["higher", "lower", "neutral"]
    threshold: str
    values: dict[str, RatioValueOut]  # fiscal year → value, for every year in RatiosOut.years


class RatioGroupOut(BaseModel):
    group: str
    label: str
    ratios: list[RatioSeriesOut]


class CheckOut(BaseModel):
    id: str
    label_he: str
    status: Literal["passed", "failed", "not_applicable"]
    cells: list[str]
    left: str | None = None
    right: str | None = None
    difference: str | None = None
    reason: str | None = None


class RatiosOut(BaseModel):
    ticker: str
    template: str
    currency: str | None
    years: list[int]  # newest first; up to fin_max_years contiguous years ending at the latest
    as_of: str | None
    groups: list[RatioGroupOut]
    checks: dict[str, list[CheckOut]]  # fiscal year → data-quality check results


# -- company report (company-report-spec): 1-10 scores per axis and year, derived from the ratios


Tone = Literal["positive", "negative", "neutral"]
Direction = Literal["up", "down", "flat"]


class ReportSector(BaseModel):
    id: str = Field(description="The statement template: industrial, bank or insurer")
    name: str


class ReportCompany(BaseModel):
    ticker: str
    name_he: str
    name_en: str | None = None
    logo_url: str | None = None
    exchange: str
    currency: str
    sector: ReportSector


class ReportInfo(BaseModel):
    type: Literal["annual"] = "annual"
    fiscal_year: int
    period_end: str
    published_at: str


class ReportSummary(BaseModel):
    text: str


class ScoreTrend(BaseModel):
    direction: Direction
    delta: int
    tone: Tone


class ScoreDriver(BaseModel):
    label: str
    tone: Tone


class AxisScore(BaseModel):
    fiscal_year: int
    value: int | None = Field(description="1-10, higher is better; null when no ratio has a value")
    sector_median: float | None = None
    trend: ScoreTrend | None = None
    driver: ScoreDriver | None = None


class ProfileAxis(BaseModel):
    id: str
    label: str
    status: Literal["ok", "insufficient_data"]
    detail_url: str
    scores: list[AxisScore]


class ReportProfile(BaseModel):
    axes: list[ProfileAxis]


class ReportEvent(BaseModel):
    id: str
    date: str
    date_precision: Literal["day", "month"]
    type: Literal[
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
    title: str
    summary: str
    importance: int = Field(ge=1, le=3)
    tone: Tone
    source_url: str | None = None


class MetricPoint(BaseModel):
    fiscal_year: int
    value: str | None = Field(description="Decimal string")


class MetricChange(BaseModel):
    direction: Direction
    pct: float | None = None
    tone: Tone


class KeyMetric(BaseModel):
    id: str
    label: str
    format: Literal["currency", "percent", "ratio", "count"]
    currency: str | None = None
    series: list[MetricPoint]
    change: MetricChange | None = None


class ReportWarning(BaseModel):
    code: str
    message: str


class CompanyReportOut(BaseModel):
    schema_version: str = "1.0"
    generated_at: str
    mode: Literal["cached", "live"]
    company: ReportCompany
    report: ReportInfo
    summary: ReportSummary
    years: list[int] = Field(description="Up to three fiscal years, oldest first")
    profile: ReportProfile
    events: list[ReportEvent]
    key_metrics: list[KeyMetric]
    warnings: list[ReportWarning]


class AxisFactor(BaseModel):
    label: str
    display: str
    tone: Tone


class SectorComparison(BaseModel):
    position: Literal["above", "below", "equal"]
    median: float


class AxisDetailOut(BaseModel):
    axis_id: str
    fiscal_year: int
    headline: str
    factors: list[AxisFactor]
    sector_comparison: SectorComparison | None = None
    text: str
