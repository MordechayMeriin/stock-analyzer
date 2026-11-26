"""OSINT research service: tracked tickers, cache, live switch, offline run, no filing access."""

from __future__ import annotations

import json
from datetime import date

import pytest
import respx

from stock_analyzer.companies import TrackedCompany
from stock_analyzer.errors import CompanyNotFound, LiveModeDisabled, NotCached
from stock_analyzer.osint.agents import fake_model_factory
from stock_analyzer.osint.models import AREAS
from stock_analyzer.osint.search import FakeSearch
from stock_analyzer.services import osint
from stock_analyzer.services.context import Ctx
from stock_analyzer.store import get_store

TODAY = date(2026, 11, 26)


@pytest.fixture(autouse=True)
def elal_tracked(settings):
    """ELAL is tracked through the store (added at runtime), as in the hosted deployment."""
    get_store(settings).add_tracked(
        TrackedCompany(
            ticker="ELAL", name_he="אל על", name_en="El Al Israel Airlines", fr_company_id=1, source="added"
        )
    )


class Spy:
    """Search backend and model factory that record whether they were used."""

    def __init__(self):
        self.search = FakeSearch()
        self.models = 0

    def factory(self, role, area):
        self.models += 1
        return fake_model_factory("ELAL")(role, area)


def live_ctx(settings) -> Ctx:
    return Ctx(settings, mode="live")


def test_window_start():
    assert osint.window_start(date(2026, 11, 26), 12) == date(2025, 11, 26)
    assert osint.window_start(date(2026, 3, 31), 1) == date(2026, 2, 28)
    assert osint.window_start(date(2026, 1, 15), 13) == date(2024, 12, 15)


def test_untracked_ticker_rejected_without_calls(settings):
    spy = Spy()
    with pytest.raises(CompanyNotFound):
        osint.run_research(
            live_ctx(settings), "NOPE", today=TODAY, backend=spy.search, model_factory=spy.factory
        )
    assert spy.search.calls == [] and spy.models == 0


def test_live_run_is_always_fresh_and_stores_latest(settings):
    spy = Spy()
    ctx = live_ctx(settings)
    first = osint.run_research(ctx, "elal", today=TODAY, backend=spy.search, model_factory=spy.factory)
    assert first.ticker == "ELAL" and not first.from_cache
    assert "אל על" in first.company_name
    assert [a.area for a in first.scorecard.areas] == list(AREAS)
    assert first.window_months == 36 and first.window_start == date(2023, 11, 26)
    assert first.searches_used == 6 and first.search_limit == settings.osint_max_searches
    calls = len(spy.search.calls)

    second = osint.run_research(ctx, "ELAL", today=TODAY, backend=spy.search, model_factory=spy.factory)
    assert not second.from_cache and len(spy.search.calls) == 2 * calls  # searched again
    assert ctx.store.cache("llm").get("osint:ELAL:36m:latest") is not None


def test_other_window_is_a_different_entry(settings):
    spy = Spy()
    ctx = live_ctx(settings)
    osint.run_research(ctx, "ELAL", 6, today=TODAY, backend=spy.search, model_factory=spy.factory)
    assert osint.cached_result(ctx, "ELAL", 36) is None
    assert osint.cached_result(ctx, "ELAL", 6) is not None


def test_duplicate_company_names_are_merged(settings):
    get_store(settings).add_tracked(
        TrackedCompany(ticker="DUP", name_he="Dup Ltd.", name_en="Dup Ltd.", fr_company_id=2, source="added")
    )
    spy = Spy()
    result = osint.run_research(
        live_ctx(settings), "DUP", today=TODAY, backend=spy.search, model_factory=spy.factory
    )
    assert result.company_name == "Dup Ltd."


def test_live_disabled_without_stored_result_fails_without_calls(settings):
    spy = Spy()
    off = settings.model_copy(update={"allow_live": False})
    with pytest.raises(LiveModeDisabled, match="ALLOW_LIVE=false"):
        osint.run_research(Ctx(off), "ELAL", today=TODAY, backend=spy.search, model_factory=spy.factory)
    assert spy.search.calls == [] and spy.models == 0


def test_live_disabled_serves_latest_stored_result(settings):
    spy = Spy()
    osint.run_research(
        live_ctx(settings), "ELAL", today=date(2026, 11, 20), backend=spy.search, model_factory=spy.factory
    )
    calls = len(spy.search.calls)
    off = settings.model_copy(update={"allow_live": False})
    stored = osint.run_research(Ctx(off), "ELAL", today=TODAY, backend=spy.search, model_factory=spy.factory)
    assert stored.from_cache and stored.run_date == date(2026, 11, 20)
    assert len(spy.search.calls) == calls


def test_cached_mode_serves_stored_or_explains(settings):
    spy = Spy()
    with pytest.raises(NotCached):
        osint.run_research(Ctx(settings), "ELAL", today=TODAY, backend=spy.search, model_factory=spy.factory)
    assert spy.search.calls == []
    osint.run_research(live_ctx(settings), "ELAL", today=TODAY, backend=spy.search, model_factory=spy.factory)
    assert osint.run_research(
        Ctx(settings), "ELAL", today=TODAY, backend=spy.search, model_factory=spy.factory
    ).from_cache


@respx.mock  # no routes: any HTTP request would fail the test
def test_fake_mode_runs_offline(settings):
    fake = settings.model_copy(update={"llm_fake": True, "openrouter_api_key": None})
    result = osint.run_research(Ctx(fake), "ELAL", today=TODAY)
    assert result.model.startswith("fake/") and len(result.scorecard.areas) == 6
    assert result.findings and result.scorecard.summary_he
    # stored under its own key: a fake result is never served to a real run
    assert Ctx(fake).store.cache("llm").get("osint-fake:ELAL:36m:latest") is not None
    assert osint.cached_result(Ctx(settings), "ELAL", 36) is None


def test_run_never_touches_filings_or_stored_reports(settings, monkeypatch):
    store = get_store(settings)

    def forbidden(*args, **kwargs):
        raise AssertionError("OSINT research read filing data")

    for name in ("load_report", "list_reports", "cached_filing_id", "save_financials"):
        monkeypatch.setattr(store, name, forbidden)
    real_cache = store.cache

    def cache(namespace):
        if namespace != "llm":
            raise AssertionError(f"OSINT research used the {namespace!r} cache")
        return real_cache(namespace)

    monkeypatch.setattr(store, "cache", cache)
    monkeypatch.setattr(Ctx, "fr", property(lambda self: forbidden()))

    spy = Spy()
    ctx = Ctx(settings, mode="live", _store=store)
    result = osint.run_research(ctx, "ELAL", today=TODAY, backend=spy.search, model_factory=spy.factory)
    assert result.findings


def test_usage_records_have_osint_purposes(settings):
    spy = Spy()
    osint.run_research(live_ctx(settings), "ELAL", today=TODAY, backend=spy.search, model_factory=spy.factory)
    path = settings.logs_dir / "llm.jsonl"
    purposes = {json.loads(line)["purpose"] for line in path.read_text().splitlines()}
    assert "osint-search" in purposes and "osint-agent:osint_orchestrator" in purposes
