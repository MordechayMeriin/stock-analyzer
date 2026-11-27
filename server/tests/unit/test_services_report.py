"""Company report service: radar scores from cached ratios, key metrics, events, axis detail."""

import json
from datetime import date

import pytest
from jsonschema import Draft202012Validator

from stock_analyzer.errors import AxisNotFound, YearNotFound
from stock_analyzer.osint.models import ResearchResult
from stock_analyzer.services import report
from stock_analyzer.services.context import Ctx
from tests.conftest import SERVER_ROOT, seed_bank_and_insurer, seed_malam

# The one copy of the contract: the spec's JSON Schema, which the web client checks its fixtures against.
SCHEMA_PATH = SERVER_ROOT.parent / "web" / "src" / "features" / "report" / "company-report.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
TODAY = date(2026, 11, 26)


def schema_errors(r) -> list[str]:
    payload = json.loads(r.model_dump_json())
    return [e.message for e in Draft202012Validator(SCHEMA).iter_errors(payload)]


@pytest.fixture
def malam(settings):
    seed_malam(settings)
    return report.company_report(Ctx(settings), "MLTM", today=TODAY)


def test_malam_report_shape(malam):
    r = malam
    assert r.years == [2023, 2024, 2025] and r.report.fiscal_year == 2025
    assert [a.id for a in r.profile.axes] == [
        "stability",
        "safety",
        "growth",
        "profitability",
        "cash_quality",
    ]
    assert r.company.sector.id == "industrial" and r.company.currency == "ILS" and r.mode == "cached"
    assert r.report.period_end == "2025-12-31" and r.report.published_at
    assert r.events == []  # no stored OSINT result
    assert all(a.detail_url == f"/api/companies/MLTM/report/axes/{a.id}" for a in r.profile.axes)


def test_scores_are_ints_or_null_with_consistent_trends(malam):
    for axis in malam.profile.axes:
        assert [s.fiscal_year for s in axis.scores] == [2023, 2024, 2025]
        assert axis.scores[0].trend is None and axis.scores[0].driver is None
        for s in axis.scores:
            assert s.value is None or (isinstance(s.value, int) and 1 <= s.value <= 10)
        for prev, cur in zip(axis.scores, axis.scores[1:], strict=False):
            if prev.value is None or cur.value is None:
                assert cur.trend is None
                continue
            delta = cur.value - prev.value
            assert cur.trend.delta == delta
            assert cur.trend.direction == ("up" if delta > 0 else "down" if delta < 0 else "flat")
            assert cur.trend.tone == ("positive" if delta > 0 else "negative" if delta < 0 else "neutral")
            if cur.driver:
                assert len(cur.driver.label) <= 28 and cur.driver.tone == cur.trend.tone
        assert axis.status == ("ok" if any(s.value is not None for s in axis.scores) else "insufficient_data")


def test_key_metrics(malam):
    ids = [m.id for m in malam.key_metrics]
    assert len(ids) <= 8 and {"revenue", "net_income_parent"} <= set(ids)
    revenue = next(m for m in malam.key_metrics if m.id == "revenue")
    assert [p.fiscal_year for p in revenue.series] == [2023, 2024, 2025]
    assert all(p.value is None or isinstance(p.value, str) for p in revenue.series)
    assert revenue.currency == "ILS" and revenue.change is not None


def test_payload_validates_against_the_spec_schema(malam):
    assert schema_errors(malam) == []


def test_bank_has_its_own_axes(settings):
    seed_bank_and_insurer(settings)
    r = report.company_report(Ctx(settings), "LUMI", today=TODAY)
    assert r.company.sector.id == "bank"
    assert [a.id for a in r.profile.axes] == ["profitability", "safety", "credit", "liquidity", "growth"]
    assert schema_errors(r) == []


def test_insurer_has_three_axes(settings):
    seed_bank_and_insurer(settings)
    r = report.company_report(Ctx(settings), "HARL", today=TODAY)
    assert [a.id for a in r.profile.axes] == ["profitability", "safety", "growth"]
    assert schema_errors(r) == []


def test_stale_report_warning(settings):
    seed_malam(settings)
    r = report.company_report(Ctx(settings), "MLTM", today=date(2028, 1, 1))
    assert "stale_report" in [w.code for w in r.warnings]


def test_axis_detail(settings):
    seed_malam(settings)
    ctx = Ctx(settings)
    d = report.axis_detail(ctx, "MLTM", "stability")
    assert d.axis_id == "stability" and d.fiscal_year == 2025 and d.sector_comparison is None
    assert [f.label for f in d.factors] == ["שיעור רווח תפעולי", "יחס שוטף"]
    assert d.factors[0].display.endswith("%") and d.factors[1].display.endswith("x")
    assert "ממוצע" in d.text and "(0%=1, 15%=10)" in d.text and "(0.8=1, 2.0=10)" in d.text
    assert d.headline.startswith("יציבות:") and len(d.headline) <= 80
    assert report.axis_detail(ctx, "MLTM", "stability", 2023).fiscal_year == 2023


def test_axis_detail_errors(settings):
    seed_malam(settings)
    ctx = Ctx(settings)
    with pytest.raises(AxisNotFound):
        report.axis_detail(ctx, "MLTM", "valuation")
    with pytest.raises(YearNotFound):
        report.axis_detail(ctx, "MLTM", "safety", 2019)


def finding(i, published_at, **kw):
    base = {
        "id": f"f{i}",
        "area": "news",
        "claim": "x" * 120,
        "signal": "positive",
        "confidence": "high",
        "source_url": "https://example.com/a",
        "source_title": "כותרת",
        "published_at": published_at,
        "derived_from_filing": False,
    }
    return base | kw


def osint_result(findings):
    return ResearchResult.model_validate(
        {
            "ticker": "MLTM",
            "company_name": "x",
            "run_date": "2026-11-01",
            "window_months": 36,
            "window_start": "2023-11-01",
            "model": "m",
            "scorecard": {
                "overall_label": "stable",
                "overall_rationale": "x",
                "areas": [],
                "risks": [],
                "strengths": [],
                "summary_he": "x",
            },
            "findings": findings,
            "dropped": {},
            "searches_used": 0,
            "search_limit": 0,
            "cost_usd": None,
        }
    )


def test_events_from_stored_osint_result():
    result = osint_result(
        [
            finding(1, "2026-03-25"),
            finding(2, "2026-09", area="credit", confidence="low", signal="negative"),
            finding(3, "2020-01-01"),  # outside 36 months
            finding(4, None),  # undated
            finding(5, "2026-12-31"),  # in the future
        ]
    )
    events = report.events_from(result, TODAY)
    assert [e.id for e in events] == ["ev-f2", "ev-f1"]
    assert events[0].date == "2026-09" and events[0].date_precision == "month"
    assert events[0].type == "financing" and events[0].importance == 1 and events[0].tone == "negative"
    assert events[1].date_precision == "day" and events[1].importance == 3 and events[1].type == "other"
    assert len(events[1].summary) <= 80 and events[1].summary.endswith("…")
