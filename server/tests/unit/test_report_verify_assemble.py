"""Verification and assembly of the company report (company-report spec, design D3-D4)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest

from stock_analyzer.companies import TrackedCompany
from stock_analyzer.report.assemble import assemble, details_of
from stock_analyzer.report.models import RaterOutput
from stock_analyzer.report.verify import verify_rating
from stock_analyzer.story.facts import FactRegistry
from tests.unit.report_helpers import YEARS, rated_year, rater_output, story_run

SCHEMA = (
    Path(__file__).resolve().parents[3] / "web" / "src" / "features" / "report" / "company-report.schema.json"
)
COMPANY = TrackedCompany(
    ticker="ELAL", name_he="אל על", name_en="El Al Israel Airlines Ltd.", fr_company_id=6759
)


def check(data: dict) -> list[str]:
    run = story_run()
    return verify_rating(RaterOutput.model_validate(data), FactRegistry(run.facts), YEARS)


def with_year(axis: str, fy: int, **year) -> dict:
    data = rater_output()
    for a in data["axes"]:
        if a["axis_id"] == axis:
            a["years"] = [
                rated_year(axis, y, **year) if y == fy else v for y, v in zip(YEARS, a["years"], strict=True)
            ]
    return data


def test_good_output_passes():
    assert check(rater_output()) == []


def test_unknown_evidence_id():
    errors = check(with_year("growth", 2025, value=3, evidence=["RATIO:roe:2019"]))
    assert any("RATIO:roe:2019" in e for e in errors)


def test_unknown_factor_id_and_factor_without_value():
    bad = [
        {"label": "x", "fact_id": "FIN:nope:2025", "tone": "neutral"},
        {"label": "y", "fact_id": "FIN:cfo:2023", "tone": "neutral"},
    ]
    errors = check(with_year("safety", 2023, factors=bad))
    assert any("FIN:nope:2025" in e for e in errors)
    assert any("FIN:cfo:2023" in e and "no value" in e for e in errors)


def test_value_out_of_range():
    assert any("outside 1-10" in e for e in check(with_year("growth", 2024, value=11)))
    assert any("outside 1-10" in e for e in check(with_year("growth", 2024, value=0)))


def test_null_value_is_allowed():
    assert check(with_year("stability", 2023, value=None)) == []


def test_missing_axis_and_year():
    data = rater_output()
    data["axes"] = data["axes"][1:]
    assert any("axis stability" in e for e in check(data))
    data = rater_output()
    data["axes"][0]["years"] = data["axes"][0]["years"][:2]
    assert any("fiscal year 2025" in e for e in check(data))


def test_labels_over_limits():
    errors = check(
        with_year("growth", 2025, value=3, driver_label="א" * 29, headline="ב" * 81, text="ג" * 601)
    )
    assert sum("characters, the limit" in e for e in errors) == 3
    data = rater_output(summary="ד" * 161)
    data["events"][0]["title"] = "ה" * 41
    assert sum("characters, the limit" in e for e in check(data)) == 2


def test_unknown_event_type_and_bad_date():
    out = RaterOutput.model_validate(rater_output())
    out.events[0].type = "party"  # bypasses the schema, as a model's raw output could
    out.events[0].date = "2023-10-07"  # day date with month precision
    run = story_run()
    errors = verify_rating(out, FactRegistry(run.facts), YEARS)
    assert any("unknown type 'party'" in e for e in errors)
    assert any("does not match precision" in e for e in errors)


# ---------------------------------------------------------------- assembly


def build(data: dict | None = None):
    run = story_run()
    rating = RaterOutput.model_validate(data or rater_output())
    report = assemble(
        run, rating, COMPANY, mode="live", published_at="2026-03-26", now=datetime(2026, 11, 27, tzinfo=UTC)
    )
    return run, rating, report


def test_report_matches_the_web_schema():
    _, _, report = build()
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(report.model_dump(mode="json"), schema)


def test_axes_order_and_trends():
    _, _, report = build()
    assert [a.id for a in report.profile.axes] == [
        "stability",
        "safety",
        "revenue_quality",
        "growth",
        "profitability",
    ]
    growth = next(a for a in report.profile.axes if a.id == "growth")
    first, _, last = growth.scores
    assert first.trend is None and first.driver is None
    assert last.trend.model_dump() == {"direction": "down", "delta": -6, "tone": "negative"}
    assert last.driver is not None and len(last.driver.label) <= 28
    assert all(s.sector_median is None for a in report.profile.axes for s in a.scores)


def test_null_score_marks_insufficient_data():
    _, _, report = build(with_year("stability", 2023, value=None))
    stability = report.profile.axes[0]
    assert stability.status == "insufficient_data"
    assert stability.scores[0].value is None
    assert stability.scores[1].trend is None  # nothing to compare against


def test_factor_display_is_the_facts_rendered_value():
    run, rating, _ = build()
    details = details_of(run, rating)
    d = next(d for d in details if d.axis_id == "profitability" and d.fiscal_year == 2025)
    assert d.factors[0].display == "15.84%"
    assert d.sector_comparison is None


def test_key_metrics_and_events():
    _, _, report = build()
    by_id = {m.id: m for m in report.key_metrics}
    assert set(by_id) == {"revenue", "operating_margin", "net_income_consolidated", "cfo"}
    assert by_id["revenue"].currency == "USD"
    assert by_id["cfo"].series[0].value is None  # missing 2023 value stays null
    assert by_id["revenue"].series[-1].value == "3476000000"
    assert report.events[0].date == "2023-10" and report.events[0].importance == 3
    assert report.company.currency == "USD" and report.years == [2023, 2024, 2025]


@pytest.mark.parametrize("prev,cur,direction", [(5, 5, "flat"), (3, 7, "up")])
def test_trend_directions(prev, cur, direction):
    from stock_analyzer.report.assemble import trend_of

    assert trend_of(prev, cur).direction == direction
