"""Ticker autocomplete: ranking, tracked merge, normalisation, fallback and no-network guarantees."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from stock_analyzer.api.main import create_app
from stock_analyzer.cli import app as cli_app
from stock_analyzer.config import reset_settings_cache
from stock_analyzer.ingest.fr_client import FRClient
from stock_analyzer.services import tickers
from stock_analyzer.services.context import Ctx
from tests.conftest import FIXTURES, seed_fr_cache


@pytest.fixture(autouse=True)
def _fresh_memo():
    tickers.clear_memo()
    yield
    tickers.clear_memo()


def _seed(settings) -> None:
    for page in (1, 2):
        body = json.loads((FIXTURES / f"tase_directory_page{page}.json").read_text(encoding="utf-8"))
        seed_fr_cache(settings, "/companies/", FRClient.listing_params(settings.fr_country, page), body)


@pytest.fixture
def ctx(settings):
    _seed(settings)
    c = Ctx(settings)
    yield c
    c.close()


def _t(ctx, q, limit=8):
    return [h.ticker for h in tickers.search(ctx, q, limit).results]


def test_directory_skips_rows_without_ticker(ctx):
    entries = tickers.directory(ctx)
    assert len(entries) == 5 and all(e.ticker for e in entries)


def test_ranking(ctx):
    assert _t(ctx, "mltm")[0] == "MLTM"  # exact ticker
    assert _t(ctx, "es")[0] == "ESLT"  # ticker prefix
    assert _t(ctx, "elbit")[0] == "ESLT"  # name starts with
    assert _t(ctx, "galil") == ["DELG"]  # word in name
    assert _t(ctx, "ndustr") == ["DELG"]  # substring
    assert _t(ctx, "discont")[:1] == []  # no fuzzy
    assert _t(ctx, "דיסקונט") == ["DSCT"]  # Hebrew name prefix


def test_tracked_first_with_hebrew_name(ctx):
    res = tickers.search(ctx, "מלם").results
    assert [h.ticker for h in res] == ["MLTM", "MLMS"]  # same rank: tracked first
    assert res[0].tracked and res[0].name_he == "מלם תים" and res[0].fr_company_id == 6901
    assert not res[1].tracked and res[1].name_he == 'מלם מערכות בע"מ' and res[1].name_en is None
    english = tickers.search(ctx, "elbit").results[0]
    assert english.name_en == "Elbit Systems Ltd." and english.name_he == "אלביט מערכות"  # TASE's name


def test_normalisation(ctx):
    assert _t(ctx, 'דיסקונט לישראל בע"מ') == ["DSCT"]
    assert _t(ctx, "דיסקונט לישראל בעמ") == ["DSCT"]
    assert _t(ctx, "Delta-Galil Industries Ltd.") == ["DELG"]
    assert _t(ctx, "malam team") == ["MLTM"]


def test_tracked_only_fallback(settings):
    c = Ctx(settings)
    res = tickers.search(c, "mltm")
    c.close()
    assert [h.ticker for h in res.results] == ["MLTM"]
    assert res.directory.source == "tracked_only" and res.directory.size == 0
    assert res.directory.fetched_at is None


def test_directory_info_and_limit(ctx):
    res = tickers.search(ctx, "l", 2)
    assert len(res.results) <= 2
    assert res.directory.source == "directory" and res.directory.size == 5 and res.directory.fetched_at
    assert len(tickers.search(ctx, "e", 1).results) == 1


def test_short_query_matches_tickers_only(ctx):
    assert _t(ctx, "m")[:1] == ["MLTM"]
    assert _t(ctx, "d") == ["DSCT", "DELG"]  # ticker prefixes only, not names containing d


def test_live_mode_get_makes_no_network_call(settings, monkeypatch):
    # Nothing stored: a live-mode request would have to go to the provider.
    def boom(*a, **k):
        raise AssertionError("network call")

    monkeypatch.setattr(FRClient, "_send", boom)
    live = Ctx(settings.model_copy(update={"allow_live": True}), mode="live")
    try:
        res = tickers.search(live, "mltm")
    finally:
        live.close()
    assert res.directory.source == "tracked_only"


def test_route(settings):
    _seed(settings)
    with TestClient(create_app(settings)) as c:
        body = c.get("/api/tickers", params={"q": "elbit", "limit": 3, "mode": "live"}).json()
        assert body["results"][0]["ticker"] == "ESLT" and body["directory"]["source"] == "directory"
        assert body["results"][0].keys() >= {
            "ticker",
            "name_he",
            "name_en",
            "fr_company_id",
            "isin",
            "tracked",
        }
        assert c.get("/api/tickers", params={"q": ""}).status_code == 422
        assert c.get("/api/tickers", params={"q": "x" * 61}).status_code == 422
        assert c.get("/api/tickers", params={"q": "a", "limit": 21}).status_code == 422


def test_cli_refresh_refused_when_live_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ALLOW_LIVE", "false")
    reset_settings_cache()
    r = CliRunner().invoke(cli_app, ["companies", "directory", "--refresh"])
    assert r.exit_code == 1 and "live_disabled" in r.output
    r = CliRunner().invoke(cli_app, ["companies", "directory"])
    assert r.exit_code == 0 and "0 companies" in r.output
    reset_settings_cache()


def test_security_number_from_israeli_isin():
    assert tickers.security_number("IL0006290147") == 629014  # Teva
    assert tickers.security_number("US8816242098") is None
    assert tickers.security_number(None) is None


def test_hebrew_tase_name_is_searchable(ctx):
    # Elbit Systems' ISIN carries TASE security number 1081124, listed as "אלביט מערכות".
    hit = tickers.search(ctx, "אלביט").results[0]
    assert (hit.ticker, hit.name_he, hit.name_en) == ("ESLT", "אלביט מערכות", "Elbit Systems Ltd.")
    assert tickers.search(ctx, "מערכות").results[0].ticker == "ESLT"  # a word inside the name
