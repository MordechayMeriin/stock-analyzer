"""Data models for OSINT research (osint-research spec, design D4-D5).

``Finding``, ``AreaReport`` and ``Scorecard`` are agent output types, so they have no default values (the
SDK sends them as strict JSON schemas). ``KeptFinding``, ``ResearchResult`` and ``RunState`` are built in
code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from stock_analyzer.osint.blocklist import Blocklist

Area = Literal["news", "market", "credit", "operations", "labor_government", "competition_macro"]
AREAS: tuple[Area, ...] = ("news", "market", "credit", "operations", "labor_government", "competition_macro")

AREA_INFO: dict[Area, tuple[str, str]] = {
    "news": (
        "חדשות ואירועים",
        "Recent news and events about the company: management changes, strategy, deals, incidents, "
        "legal or regulatory actions, and public controversies.",
    ),
    "market": (
        "איתותי שוק",
        "Market signals: share price trend and volatility, market value, trading volume, short interest, "
        "and the yields and spreads of the company's bonds traded on the Tel Aviv Stock Exchange (TASE).",
    ),
    "credit": (
        "דירוג אשראי ותחזיות אנליסטים",
        "Credit ratings and outlooks (S&P Maalot, Midroog and international agencies), analyst "
        "recommendations, price targets and published forecasts for the company.",
    ),
    "operations": (
        "תפעול וביקוש",
        "Operations and demand: passenger traffic and market share (for example Israel Airports Authority "
        "statistics), routes, fleet and aircraft orders, delays and cancellations, customer complaints.",
    ),
    "labor_government": (
        "עבודה וממשלה",
        "Labor relations (unions, strikes, wage agreements) and government involvement: regulation, "
        "state holdings or special shares, subsidies, security requirements and policy decisions.",
    ),
    "competition_macro": (
        "תחרות, מאקרו וגאופוליטיקה",
        "Competition (rivals entering or leaving the market, pricing), macroeconomics (fuel prices, "
        "exchange rates, interest rates, tourism) and geopolitics (war, security, travel warnings).",
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
