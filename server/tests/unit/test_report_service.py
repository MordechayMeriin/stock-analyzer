"""The story report service: cached reads, live builds, one repair, saving per story run, story first."""

from __future__ import annotations

import pytest

from stock_analyzer.agents_model import FakeAgentModels
from stock_analyzer.companies import TrackedCompany
from stock_analyzer.errors import AxisNotFound, NotCached, ReportVerificationFailed
from stock_analyzer.report.rater import PURPOSE
from stock_analyzer.services import report as company_report_service
from stock_analyzer.services import story_report as report_service
from stock_analyzer.services.context import Ctx
from tests.unit.report_helpers import rater_output, story_run

ELAL = TrackedCompany(
    ticker="ELAL", name_he="אל על", name_en="El Al Israel Airlines Ltd.", fr_company_id=6759, source="added"
)


@pytest.fixture
def seeded(settings):
    ctx = Ctx(settings=settings)
    ctx.store.add_tracked(ELAL)
    ctx.store.save_story_run("ELAL", story_run().model_dump(mode="json"))
    return settings


def live(settings) -> Ctx:
    return Ctx(settings=settings, mode="live")


def cached(settings) -> Ctx:
    return Ctx(settings=settings, mode="cached")


def bad_output() -> dict:
    data = rater_output()
    data["axes"][3]["years"][2]["evidence"] = ["RATIO:roe:2019"]
    return data


def test_cached_miss_says_use_live_mode(seeded):
    with pytest.raises(NotCached, match="live mode"):
        report_service.get_report(cached(seeded), "ELAL")


def test_no_story_run_is_not_cached(settings):
    ctx = Ctx(settings=settings, mode="live")
    ctx.store.add_tracked(ELAL)
    with pytest.raises(NotCached, match="story"):
        report_service.get_report(ctx, "ELAL")


def test_live_build_saves_and_repeat_is_identical(seeded):
    fakes = FakeAgentModels(settings=seeded, script={PURPOSE: [rater_output()]})
    first = report_service.get_report(live(seeded), "ELAL", models=fakes)
    assert first.mode == "live"
    assert [a.id for a in first.profile.axes][0] == "stability"
    assert len(fakes.turns) == 1

    again = report_service.get_report(cached(seeded), "ELAL")
    assert again.mode == "cached"
    assert again.model_dump(exclude={"mode"}) == first.model_dump(exclude={"mode"})
    again_live = report_service.get_report(live(seeded), "ELAL", models=fakes)
    assert again_live.mode == "cached" and len(fakes.turns) == 1  # no second LLM call


def test_one_repair_then_success(seeded):
    fakes = FakeAgentModels(settings=seeded, script={PURPOSE: [bad_output(), rater_output()]})
    report_service.get_report(live(seeded), "ELAL", models=fakes)
    assert len(fakes.turns) == 2
    assert "RATIO:roe:2019" in str(fakes.turns[1].input)  # the errors went back to the rater


def test_second_failure_saves_nothing(seeded):
    fakes = FakeAgentModels(settings=seeded, script={PURPOSE: [bad_output(), bad_output()]})
    with pytest.raises(ReportVerificationFailed) as exc:
        report_service.get_report(live(seeded), "ELAL", models=fakes)
    assert any("RATIO:roe:2019" in e for e in exc.value.errors)
    with pytest.raises(NotCached):
        report_service.get_report(cached(seeded), "ELAL")


def test_newer_story_run_gets_a_new_report(seeded):
    fakes = FakeAgentModels(settings=seeded, script={PURPOSE: [rater_output(), rater_output(summary="חדש")]})
    report_service.get_report(live(seeded), "ELAL", models=fakes)
    newer = story_run("run2").model_copy(update={"created_at": "2026-11-28T00:00:00+00:00"})
    Ctx(settings=seeded).store.save_story_run("ELAL", newer.model_dump(mode="json"))
    with pytest.raises(NotCached):
        report_service.get_report(cached(seeded), "ELAL")
    assert report_service.get_report(live(seeded), "ELAL", models=fakes).summary.text == "חדש"


def test_axis_detail(seeded):
    fakes = FakeAgentModels(settings=seeded, script={PURPOSE: [rater_output()]})
    report_service.get_report(live(seeded), "ELAL", models=fakes)
    d = report_service.get_axis_detail(cached(seeded), "ELAL", "profitability", 2025)
    assert d.factors[0].display == "15.84%"
    with pytest.raises(AxisNotFound):
        report_service.get_axis_detail(cached(seeded), "ELAL", "valuation", 2025)
    with pytest.raises(AxisNotFound):
        report_service.get_axis_detail(cached(seeded), "ELAL", "growth", 2019)


def test_company_report_serves_the_story_report_first(seeded):
    fakes = FakeAgentModels(settings=seeded, script={PURPOSE: [rater_output()]})
    report_service.get_report(live(seeded), "ELAL", models=fakes)
    out = company_report_service.company_report(cached(seeded), "ELAL")
    assert [a.id for a in out.profile.axes] == [
        "stability",
        "safety",
        "revenue_quality",
        "growth",
        "profitability",
    ]
    assert out.events[0].tone == "negative" and out.events[0].summary == ""
    growth = next(a for a in out.profile.axes if a.id == "growth")
    assert growth.scores[2].trend.delta == -6
    detail = company_report_service.axis_detail(cached(seeded), "ELAL", "profitability", None)
    assert detail.fiscal_year == 2025 and detail.factors[0].display == "15.84%"
    with pytest.raises(AxisNotFound):
        company_report_service.axis_detail(cached(seeded), "ELAL", "valuation", 2025)


def test_company_report_falls_back_to_ratios_without_a_story_report(seeded, monkeypatch):
    calls = []
    monkeypatch.setattr(
        company_report_service,
        "analyze",
        lambda ctx, t: calls.append(t) or (_ for _ in ()).throw(NotCached("ratios")),
    )
    with pytest.raises(NotCached, match="ratios"):
        company_report_service.company_report(cached(seeded), "ELAL")
    assert calls == ["ELAL"]  # no saved story report in cached mode: the ratio path ran
