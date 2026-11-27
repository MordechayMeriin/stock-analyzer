"""A small saved story run and rater outputs for the report tests (shaped like El Al's)."""

from __future__ import annotations

from typing import Any

from stock_analyzer.story.agents import CompanyProfile, ProfileItem
from stock_analyzer.story.facts import Fact, FactRegistry
from stock_analyzer.story.models import Finding, Story, StoryParagraph
from stock_analyzer.story.pipeline import RenderedStory, StoryRun, StoryUsage
from stock_analyzer.story.render import render_finding, render_paragraph

YEARS = [2023, 2024, 2025]


def _fin(code: str, name: str, values: dict[int, str | None]) -> list[Fact]:
    return [
        Fact(
            fact_id=f"FIN:{code}:{y}",
            kind="FIN",
            name_he=name,
            unit="money",
            years=[y],
            value=v,
            currency="USD",
            code=code,
        )
        for y, v in values.items()
    ]


def _ratio(code: str, name: str, values: dict[int, str | None]) -> list[Fact]:
    return [
        Fact(
            fact_id=f"RATIO:{code}:{y}",
            kind="RATIO",
            name_he=name,
            unit="percent",
            years=[y],
            value=v,
            code=code,
        )
        for y, v in values.items()
    ]


def facts() -> list[Fact]:
    return [
        *_fin("revenue", "הכנסות", {2023: "2503100000", 2024: "3431800000", 2025: "3476000000"}),
        *_fin(
            "net_income_consolidated", "רווח נקי", {2023: "116700000", 2024: "544900000", 2025: "410300000"}
        ),
        *_fin("cfo", "תזרים מפעילות שוטפת", {2023: None, 2024: "1446500000", 2025: "1046200000"}),
        *_ratio("operating_margin", "שיעור רווח תפעולי", {2023: "0.1068", 2024: "0.2252", 2025: "0.1584"}),
        *_ratio("revenue_growth", "צמיחה בהכנסות", {2023: "0.2605", 2024: "0.3710", 2025: "0.0129"}),
        *_ratio("equity_to_assets", "הון למאזן", {2023: "-0.0630", 2024: "0.1205", 2025: "0.2096"}),
    ]


def story_run(run_id: str = "run1") -> StoryRun:
    fs = facts()
    reg = FactRegistry(fs)
    story = Story(
        what_it_does=[StoryParagraph(text_he="אל על מובילה נוסעים ומטען.", paragraph_ids=["p1"])],
        what_changed=[
            StoryParagraph(
                text_he="ההכנסות עלו ל־{{FIN:revenue:2024}}, ושיעור הרווח התפעולי ל־{{RATIO:operating_margin:2024}}.",
                paragraph_ids=["p2"],
            )
        ],
        story_vs_numbers=[
            Finding(
                label="consistent",
                text_he="הצמיחה ב־2025 נבעה מקיבולת.",
                fact_ids=["FIN:revenue:2025"],
                paragraph_ids=["p3"],
            )
        ],
    )
    return StoryRun(
        run_id=run_id,
        ticker="ELAL",
        as_of="2026-11-27",
        created_at="2026-11-27T02:03:32+00:00",
        years=YEARS,
        filing_ids={"2025": 61321491},
        rendered=RenderedStory(
            what_it_does=[render_paragraph(p, reg) for p in story.what_it_does],
            what_changed=[render_paragraph(p, reg) for p in story.what_changed],
            story_vs_numbers=[render_finding(f, reg) for f in story.story_vs_numbers],
            unchanged_sections=[],
        ),
        story=story,
        facts=fs,
        citations={},
        profile=CompanyProfile(
            items=[ProfileItem(topic="business_line", text_he="תעופה", fact_ids=[], paragraph_ids=["p1"])]
        ),
        change_notes=[],
        claims={},
        verification=[],
        warnings=[],
        models={},
        prompt_hashes={},
        config_hash="x",
        usage=StoryUsage(input_tokens=0, output_tokens=0, cost_usd=0.0, model_turns=0),
    )


AXIS_IDS = ["stability", "safety", "revenue_quality", "growth", "profitability"]
GROWTH = {2023: 6, 2024: 9, 2025: 3}


def rated_year(axis: str, y: int, value: int | None = 5, **over: Any) -> dict[str, Any]:
    if value is None:
        return {"fiscal_year": y, "value": None}
    d = {
        "fiscal_year": y,
        "value": value,
        "driver_label": "מרווח תפעולי עולה",
        "driver_tone": "positive",
        "evidence": [f"RATIO:operating_margin:{y}"],
        "headline": "כותרת קצרה",
        "factors": [
            {"label": "שיעור רווח תפעולי", "fact_id": f"RATIO:operating_margin:{y}", "tone": "positive"}
        ],
        "text": "הסבר קצר.",
    }
    d.update(over)
    return d


def rater_output(**over: Any) -> dict[str, Any]:
    axes = [
        {
            "axis_id": a,
            "years": [rated_year(a, y, GROWTH[y] if a == "growth" else 5) for y in YEARS],
        }
        for a in AXIS_IDS
    ]
    d = {
        "summary": "רווחיות שיא ב־2024, האטה ב־2025.",
        "axes": axes,
        "events": [
            {
                "date": "2023-10",
                "date_precision": "month",
                "type": "other",
                "title": "פרוץ המלחמה",
                "importance": 3,
                "tone": "negative",
            }
        ],
    }
    d.update(over)
    return d
