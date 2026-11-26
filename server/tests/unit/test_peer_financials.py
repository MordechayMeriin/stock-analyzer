import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from stock_analyzer.cli import app
from stock_analyzer.config import reset_settings_cache
from stock_analyzer.errors import NotCached
from stock_analyzer.ingest.fr_client import FRClient
from tests.conftest import seed_fr_cache

BASE = "https://api.financialreports.eu"
TARGET = 6901
CLASS = "0210"


def issuer(company_id, country="IL", code=CLASS, status="LISTED"):
    return {
        "id": company_id,
        "name": f"Company {company_id}",
        "ticker": None,
        "country_code": country,
        "listing_status": status,
        "sub_industry": {"code": code} if code else None,
    }


def directory_params(countries="IL", page=1):
    return {
        "countries": countries,
        "sub_industry": CLASS,
        "listing_status": "LISTED",
        "view": "full",
        "page_size": 100,
        "page": page,
    }


def directory_route(router, rows, *, countries="IL", page=1, more=False):
    params = directory_params(countries, page)
    route = router.get(url=httpx.URL(BASE + "/companies/", params=params))
    return route.respond(json={"results": rows, "next": f"?page={page + 1}" if more else None})


def test_profile_and_directory_cache(settings):
    with respx.mock(assert_all_called=True) as router, FRClient(settings) as client:
        router.get(BASE + "/companies/6901/").respond(json=issuer(TARGET, country=None, code=None))
        directory_route(router, [issuer(42)], more=True)
        directory_route(router, [issuer(21)], page=2)
        profile = client.company_profile(TARGET)
        assert profile.sub_industry is None and profile.country_code is None
        candidates = client.list_peer_candidates(["IL"], CLASS)
        assert [row.id for row in candidates] == [42, 21]
        assert candidates[0].sub_industry.code == CLASS
    with FRClient(settings, mode="cached") as cached:
        assert cached.company_profile(TARGET) == profile
        assert cached.list_peer_candidates(["IL"], CLASS) == candidates
        with pytest.raises(NotCached, match="/companies/"):
            cached.list_peer_candidates(["DE"], CLASS)


def test_selection_validates_candidates_and_deduplicates_across_markets(settings):
    from stock_analyzer.services.context import Ctx
    from stock_analyzer.services.peers import select_peers

    seed_fr_cache(settings, f"/companies/{TARGET}/", {}, issuer(TARGET))
    rows = [
        issuer(TARGET),
        issuer(12),
        issuer(14),
        issuer(3, country="GB"),
        issuer(4, code="9999"),
        issuer(5, status="DELISTED"),
    ]
    seed_fr_cache(settings, "/companies/", directory_params(), {"results": rows, "next": "?page=2"})
    seed_fr_cache(
        settings, "/companies/", directory_params(page=2), {"results": [issuer(12), issuer(10)], "next": None}
    )
    foreign = [issuer(12, "DE"), issuer(9, "DE"), issuer(7, "GB"), issuer(1, "US")]
    seed_fr_cache(settings, "/companies/", directory_params("DE,GB"), {"results": foreign, "next": None})
    ctx = Ctx(settings)
    try:
        for limit, countries, expected in [
            (2, ["US"], [10, 12]),
            (5, [], [10, 12, 14]),
            (4, ["gb", "DE", "GB", "IL"], [10, 12, 14, 7]),
        ]:
            selection = select_peers(ctx, "MLTM", limit, countries)
            assert selection.domestic_count == 3
            assert [peer.id for peer in selection.peers] == expected
    finally:
        ctx.close()


@pytest.fixture
def run_peers(settings, monkeypatch):
    monkeypatch.setenv("FR_API_KEY", "offline-test")
    monkeypatch.setenv("DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("COMPANIES_FILE", str(settings.companies_file))
    reset_settings_cache()

    def run(*args):
        return CliRunner().invoke(app, ["peer-financials", "MLTM", *args])

    return run


@pytest.mark.parametrize("target_country", ["DE", None])
def test_sole_operator_israel_default(run_peers, target_country):
    with respx.mock(assert_all_called=True) as router:
        router.get(BASE + "/companies/6901/").respond(json=issuer(TARGET, country=target_country))
        directory_route(router, [issuer(TARGET)])
        result = run_peers("--mode", "live")
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["domestic_market"] == "IL" and data["target_country"] == target_country
        assert (data["domestic_count"], data["reason"], data["peers"]) == (0, "no_domestic_matches", [])
        assert len(router.calls) == 2


@pytest.mark.parametrize("classification", [None, {}, {"code": None}])
def test_missing_classification_stops_at_profile(run_peers, classification):
    with respx.mock(assert_all_called=True) as router:
        router.get(BASE + "/companies/6901/").respond(json={**issuer(TARGET), "sub_industry": classification})
        result = run_peers("--mode", "live", "--peer-country", "GB")
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert (data["domestic_count"], data["reason"], data["peers"]) == (None, "missing_sub_industry", [])
        assert len(router.calls) == 1


def test_second_directory_page_failure_and_cache_miss(run_peers):
    with respx.mock(assert_all_called=True) as router:
        router.get(BASE + "/companies/6901/").respond(json=issuer(TARGET))
        directory_route(router, [issuer(12)], more=True)
        router.get(url=httpx.URL(BASE + "/companies/", params=directory_params(page=2))).respond(403)
        result = run_peers("--mode", "live")
        assert result.exit_code == 1 and "403" in result.output
        assert len(router.calls) == 3
        replay = run_peers()
        assert replay.exit_code == 1 and "not_cached" in replay.output and "'page': 2" in replay.output
        assert len(router.calls) == 3


def test_empty_domestic_with_foreign_fill(run_peers):
    with respx.mock(assert_all_called=True) as router:
        router.get(BASE + "/companies/6901/").respond(json=issuer(TARGET))
        directory_route(router, [])
        directory_route(router, [issuer(23, "DE")], countries="DE")
        router.get(BASE + "/companies/23/financials/", params={"fiscal_period": "FY"}).respond(
            json={"periods": []}
        )
        result = run_peers("--mode", "live", "--peer-country", "de")
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert (data["domestic_count"], data["reason"]) == (0, "no_domestic_matches")
        (peer,) = data["peers"]
        assert (peer["id"], peer["kind"], peer["country"], peer["statements"]) == (
            23,
            "international",
            "DE",
            [],
        )


@pytest.mark.parametrize("args", [("--limit", "0"), ("--peer-country", "DE,GB")])
def test_invalid_options(run_peers, args):
    with respx.mock() as router:
        assert run_peers("--mode", "live", *args).exit_code != 0
        assert len(router.calls) == 0


def test_live_statements_and_cached_replay(run_peers, monkeypatch):
    from stock_analyzer.store import FsStore

    def unexpected_edit(*args):
        pytest.fail("peer financials attempted to edit the registry")

    monkeypatch.setattr(FsStore, "add_tracked", unexpected_edit)
    monkeypatch.setattr(FsStore, "remove_tracked", unexpected_edit)
    args = ["--peer-country", "gb", "--peer-country", "DE", "--limit", "2"]
    with respx.mock(assert_all_called=True) as router:
        router.get(BASE + "/companies/6901/").respond(json=issuer(TARGET))
        directory_route(router, [issuer(TARGET), issuer(30), issuer(30)])
        directory_route(router, [issuer(7, "GB"), issuer(2, "DE")], countries="DE,GB")
        for company_id, currency in [(30, "ILS"), (2, "EUR")]:
            periods = []
            for year, code in [(2024, "revenue"), (2023, "gross_profit")]:
                statement = {
                    "statement_type": "IS",
                    "line_items": [{"code": code, "value": "9007199254740993.25"}],
                }
                periods.append({"fiscal_year": year, "fiscal_period": "FY", "statements": [statement]})
            url = httpx.URL(f"{BASE}/companies/{company_id}/financials/", params={"fiscal_period": "FY"})
            router.get(url=url).respond(json={"currency": {"code": currency}, "periods": periods})
        live = run_peers("--mode", "live", *args)
        assert live.exit_code == 0, live.output
        peers = json.loads(live.output)["peers"]
        assert [(p["id"], p["kind"], p["currency"]) for p in peers] == [
            (30, "domestic", "ILS"),
            (2, "international", "EUR"),
        ]
        for peer in peers:
            assert peer["years"] == [2024, 2023]
            items = {item["code"]: item for item in peer["statements"][0]["items"]}
            assert items["revenue"]["values"] == {"2024": "9007199254740993.25", "2023": None}
        assert len(router.calls) == 5
        replay = run_peers(*args)
        assert replay.exit_code == 0 and replay.output == live.output
        assert len(router.calls) == 5
