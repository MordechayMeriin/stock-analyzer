import json
from contextlib import closing
from datetime import date

import pytest
import respx
from typer.testing import CliRunner

from stock_analyzer.cli import app
from stock_analyzer.errors import CompanyNotFound, LiveModeDisabled, MissingSubIndustry, NotCached
from stock_analyzer.llm import FakeLLM
from stock_analyzer.osint.market import PURPOSE, IndustryClass
from stock_analyzer.osint.models import SearchHit
from stock_analyzer.osint.search import SearchResponse
from stock_analyzer.services import market_research
from stock_analyzer.services.context import Ctx
from tests.conftest import seed_fr_cache

PROFILE = "https://api.financialreports.eu/companies/6901/"
TODAY = date(2026, 11, 27)
EU_SOURCE = "https://statistics.example/eu"
IL_SOURCE = "https://industry.example/israel"
BLOCKED = "https://maya.tase.co.il/reports/123"


class ScriptedSearch:
    def __init__(self):
        self.calls = []

    async def search(self, query, max_results, exclude_domains):
        self.calls.append(query)
        assert "maya.tase.co.il" in exclude_domains
        hits = []
        if query.startswith("Europe"):
            hits = [
                SearchHit(EU_SOURCE, "EU series", "EU-only wider industry turnover"),
                SearchHit(BLOCKED, "", ""),
            ]
        if query.startswith("Israel"):
            hits = [SearchHit(IL_SOURCE, "Private operator", "A private local operator serves the industry")]
        return SearchResponse(hits=hits, summary="", model="fake/search", cost=0)


def finding(url, claim, topic, geography, **metadata):
    return {
        "topic": topic,
        "claim": claim,
        "source_urls": [url],
        "published_at": "2026-11-01",
        "geography": geography,
        "classification": None,
        "coverage": None,
        "period": None,
        "unit": None,
        "scope": "exact",
        **metadata,
    }


def draft(call):
    market = json.loads(call.user)["market"]
    if market == "Israel":
        return {
            "findings": [
                finding(
                    IL_SOURCE, "A private operator serves the market.", "participants_competition", "Israel"
                )
            ]
        }
    assert market == "Europe"
    return {
        "findings": [
            finding(
                EU_SOURCE,
                "Turnover in the wider EU group rose.",
                "demand_growth",
                "EU",
                classification="Legacy national classification",
                coverage="EU members only",
                period="2025",
                unit="EUR",
            ),
            finding(BLOCKED, "Blocked filing", "regulation_risks", "Europe"),
            finding(IL_SOURCE, "Cross-market citation", "regulation_risks", "Europe"),
            finding("https://invented.example/item", "Unverified URL", "regulation_risks", "Europe"),
            finding(EU_SOURCE, "Old evidence", "demand_growth", "EU", published_at="2020-01-01"),
        ]
    }


def test_budget_and_market_evidence(settings):
    fake_settings = settings.model_copy(update={"llm_fake": True, "osint_max_searches": 4})
    backend = ScriptedSearch()
    llm = FakeLLM(script={PURPOSE: draft})
    with closing(Ctx(fake_settings, mode="live")) as ctx:
        result = market_research.run_market_research(
            ctx, "mltm", today=TODAY, backend=backend, llm=llm, test_industry=IndustryClass(code="6220")
        )
    assert [brief.market for brief in result.markets] == ["IL", "EUROPE", "US"]
    assert [query.split()[0] for query in backend.calls] == ["Israel", "Europe", "United", "Israel"]
    assert result.searches_used == result.search_limit == 4
    assert len(llm.calls) == 2
    assert BLOCKED not in llm.calls[1].user
    il, europe, us = result.markets
    assert il.sections[1].findings[0].claim == "A private operator serves the market."
    (stat,) = europe.sections[0].findings
    assert (stat.geography, stat.coverage, stat.scope, stat.unit) == (
        "EU",
        "EU members only",
        "context",
        "EUR",
    )
    assert stat.classification == "Legacy national classification"
    assert all(section.evidence_gap for section in [europe.sections[2], *us.sections])


def test_cache_scopes_and_fake_isolation(settings):
    fake_settings = settings.model_copy(update={"llm_fake": True})
    with closing(Ctx(fake_settings, mode="live")) as ctx:
        saved = market_research.run_market_research(
            ctx,
            "MLTM",
            markets=["us", " Europe ", "US"],
            months=12,
            today=TODAY,
            backend=ScriptedSearch(),
            llm=FakeLLM(script={PURPOSE: draft}),
            test_industry=IndustryClass(code="6220"),
        )
    with closing(Ctx(fake_settings)) as ctx:
        replay = market_research.run_market_research(ctx, "mltm", markets=["EUROPE", "US"], months=12)
        assert replay == saved.model_copy(update={"from_cache": True})
        with pytest.raises(NotCached):
            market_research.run_market_research(ctx, "MLTM", markets=["US"], months=12)
        with pytest.raises(NotCached):
            market_research.run_market_research(ctx, "MLTM", markets=["US", "EUROPE"], months=6)
        with pytest.raises(ValueError, match="unknown markets"):
            market_research.run_market_research(ctx, "MLTM", markets=["CA"])
        with pytest.raises(ValueError, match="at least 1"):
            market_research.run_market_research(ctx, "MLTM", months=0)
    with closing(Ctx(settings)) as ctx, pytest.raises(NotCached):
        market_research.run_market_research(ctx, "MLTM", markets=["US", "EUROPE"], months=12)


def test_missing_ticker_and_class_stop_before_search(settings):
    backend = ScriptedSearch()
    with closing(Ctx(settings, mode="live")) as ctx, respx.mock() as router:
        with pytest.raises(CompanyNotFound):
            market_research.run_market_research(ctx, "UNKNOWN", backend=backend)
        assert len(router.calls) == 0
        router.get(PROFILE).respond(json={"id": 6901, "name": "Malam Team"})
        with pytest.raises(MissingSubIndustry, match="MLTM"):
            market_research.run_market_research(ctx, "MLTM", backend=backend)
        assert len(router.calls) == 1
        assert backend.calls == []


def test_production_cli_resolves_profile_and_replays(settings, monkeypatch):
    monkeypatch.setenv("FR_API_KEY", "test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setenv("DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("COMPANIES_FILE", str(settings.companies_file))
    backend = ScriptedSearch()
    monkeypatch.setattr(market_research, "OpenRouterSearch", lambda _: backend)
    monkeypatch.setattr(market_research, "get_llm", lambda *args, **kwargs: FakeLLM(script={PURPOSE: draft}))
    runner = CliRunner()
    args = ["market-research", "mltm", "--market", "EUROPE", "--market", "US"]
    with respx.mock(assert_all_mocked=True) as router:
        router.get(PROFILE).respond(
            json={"id": 6901, "name": "Malam Team", "sub_industry": {"code": "0210", "name": "Silviculture"}}
        )
        live = runner.invoke(app, [*args, "--mode", "live", "--json"])
        assert live.exit_code == 0, (live.output, live.exception)
        result = json.loads(live.output)
        assert result["industry"] == {"code": "0210", "name": "Silviculture"}
        assert [brief["market"] for brief in result["markets"]] == ["EUROPE", "US"]
        assert all("0210 (Silviculture)" in query for query in backend.calls)
        assert len(router.calls) == 1
        count = len(backend.calls)
        replay = runner.invoke(app, args)
        assert replay.exit_code == 0, replay.output
        assert "United States" in replay.output and EU_SOURCE in replay.output
        assert "Insufficient evidence" in replay.output
        assert len(router.calls) == 1 and len(backend.calls) == count
    assert runner.invoke(app, [*args, "--isic", "6220"]).exit_code == 2


def test_fake_live_run_can_read_cached_company_profile(settings):
    fake_settings = settings.model_copy(update={"llm_fake": True})
    seed_fr_cache(
        fake_settings,
        "/companies/6901/",
        {},
        {"id": 6901, "name": "Malam Team", "sub_industry": {"code": "6220"}},
    )
    with closing(Ctx(fake_settings, mode="live")) as ctx:
        result = market_research.run_market_research(ctx, "MLTM", markets=["US"], backend=ScriptedSearch())
        assert result.industry.code == "6220"


def test_live_disabled_and_class_override_cannot_start_production_research(settings):
    disabled = settings.model_copy(update={"allow_live": False})
    with pytest.raises(LiveModeDisabled):
        Ctx(disabled, mode="live")
    with closing(Ctx(settings, mode="live")) as ctx, respx.mock() as router:
        with pytest.raises(ValueError, match="requires offline test mode"):
            market_research.run_market_research(ctx, "MLTM", test_industry=IndustryClass(code="6220"))
        assert len(router.calls) == 0
