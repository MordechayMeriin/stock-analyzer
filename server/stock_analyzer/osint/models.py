"""Data models for OSINT research (osint-research spec, design D4-D5).

``Finding``, ``AreaReport`` and ``Scorecard`` are agent output types, so they have no default values (the
SDK sends them as strict JSON schemas). ``KeptFinding``, ``ResearchResult`` and ``RunState`` are built in
code.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from stock_analyzer.osint.blocklist import Blocklist

Area = Literal["news", "market", "credit", "operations", "labor_government", "competition_macro"]
AREAS: tuple[Area, ...] = ("news", "market", "credit", "operations", "labor_government", "competition_macro")

# Sector-neutral on purpose: the orchestrator works out the company's industry and tells each specialist
# which indicators matter for it (prompts/osint/israel_market.md has the sector guide).
AREA_INFO: dict[Area, tuple[str, str]] = {
    "news": (
        "חדשות ואירועים",
        "Recent news and events about the company: management and board changes, controlling-shareholder "
        "moves, strategy, deals and acquisitions, incidents, legal and regulatory actions, and controversies.",
    ),
    "market": (
        "איתותי שוק",
        "Market signals on the Tel Aviv Stock Exchange (TASE) and any foreign listing: share price trend and "
        "volatility, market value, trading volume, index membership, short interest, and the yields and "
        "spreads of the company's traded bonds when it has any.",
    ),
    "credit": (
        "דירוג אשראי ותחזיות אנליסטים",
        "Credit ratings and outlooks (S&P Maalot, Midroog and international agencies), analyst "
        "recommendations, price targets and published forecasts for the company.",
    ),
    "operations": (
        "תפעול וביקוש",
        "Operations and demand, using the indicators that matter in the company's industry: sales and "
        "market share, customers and contracts, capacity, projects and pipeline, production, service "
        "quality and complaints, and industry statistics published by government or trade bodies.",
    ),
    "labor_government": (
        "עבודה וממשלה",
        "Labor relations (unions, the Histadrut, strikes, wage agreements) and the state's role: the "
        "industry regulator, licences and concessions, tenders, state holdings or special shares, subsidies, "
        "taxes, and policy decisions that affect the company.",
    ),
    "competition_macro": (
        "תחרות, מאקרו וגאופוליטיקה",
        "Competition in the company's markets (rivals entering or leaving, pricing, market share), the macro "
        "factors its industry is exposed to (Bank of Israel interest rate, inflation, the shekel, input "
        "costs, demand), and geopolitics (security situation, war, sanctions, boycotts, country risk).",
    ),
}

Signal = Literal["positive", "negative", "neutral"]
Confidence = Literal["high", "medium", "low"]
Label = Literal["stable", "watch", "fragile"]
AreaLabel = Literal["stable", "watch", "fragile", "insufficient_data"]
DropReason = Literal["blocked", "not_searched", "outside_window"]


# ---------------------------------------------------------------- agent outputs


class Finding(BaseModel):
    claim: str = Field(description="One factual statement, in English or Hebrew.")
    signal: Signal = Field(description="What the fact says about the company's stability.")
    confidence: Confidence
    source_url: str = Field(description="Exact URL of a web_search result that supports the claim.")
    source_title: str
    published_at: str | None = Field(
        description="Publish date of the source, YYYY-MM-DD, or null if unknown."
    )
    derived_from_filing: bool = Field(
        description="True when the source only restates figures from the company's official reports."
    )


class AreaReport(BaseModel):
    findings: list[Finding]
    summary: str = Field(description="Two or three sentences on what the findings say for this area.")


class AreaAssessment(BaseModel):
    area: Area
    label: AreaLabel
    assessment: str = Field(description="Hebrew, two or three sentences.")
    finding_ids: list[str]


class Point(BaseModel):
    text: str = Field(description="Hebrew, one sentence.")
    finding_ids: list[str]


class Scorecard(BaseModel):
    overall_label: Label
    overall_rationale: str = Field(description="Hebrew, two or three sentences.")
    areas: list[AreaAssessment]
    risks: list[Point] = Field(description="Top three risks, most important first.")
    strengths: list[Point] = Field(description="Top three strengths, most important first.")
    summary_he: str = Field(description="Hebrew summary of the company's stability, one paragraph.")


# ---------------------------------------------------------------- built in code


class KeptFinding(Finding):
    id: str
    area: Area
    # the provider excerpt the search returned for this URL, so a story can quote numbers from it
    # (add-story-web-evidence); None when the search gave none or the result predates excerpts
    excerpt: str | None = None


class ResearchResult(BaseModel):
    ticker: str
    company_name: str
    run_date: date
    window_months: int
    window_start: date
    model: str
    scorecard: Scorecard
    findings: list[KeptFinding]
    dropped: dict[str, int]
    searches_used: int
    search_limit: int
    cost_usd: float | None
    from_cache: bool = False


ProgressStep = Literal["orchestrator", "search", "area_start", "area_done", "synthesis"]


class OsintProgress(BaseModel):
    """One progress report from a running research (streamed by the API)."""

    step: ProgressStep
    area: Area | None = None
    query: str | None = None
    searches_used: int
    search_limit: int


@dataclass
class SearchHit:
    url: str
    title: str
    snippet: str


@dataclass
class RunState:
    """Per-run state, passed to every agent and tool as the SDK run context (design D5)."""

    ticker: str
    company_names: list[str]
    window_start: date
    blocklist: Blocklist
    max_searches: int
    results_per_search: int
    searches_used: int = 0
    seen_urls: dict[str, SearchHit] = field(default_factory=dict)
    reports: list[tuple[Area, AreaReport]] = field(default_factory=list)
    cost_usd: float = 0.0
    cost_known: bool = True
    on_progress: Callable[[OsintProgress], None] | None = None

    def progress(self, step: ProgressStep, *, area: Area | None = None, query: str | None = None) -> None:
        """Report progress to the callback, if any. A failing callback never fails the (paid) run."""
        if self.on_progress is None:
            return
        try:
            self.on_progress(
                OsintProgress(
                    step=step,
                    area=area,
                    query=query,
                    searches_used=self.searches_used,
                    search_limit=self.max_searches,
                )
            )
        except Exception:  # noqa: BLE001
            pass

    def add_cost(self, cost: float | None) -> None:
        if cost is None:
            self.cost_known = False
        else:
            self.cost_usd += cost


def normalize_url(url: str) -> str:
    """Comparable form of a URL: no fragment, no trailing slash, lower-case scheme and host."""
    text = url.strip()
    text = text.split("#", 1)[0]
    if "://" in text:
        scheme, rest = text.split("://", 1)
        host, sep, path = rest.partition("/")
        text = f"{scheme.lower()}://{host.lower()}{sep}{path}"
    return text.rstrip("/")
