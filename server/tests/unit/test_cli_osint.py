"""`stock-analyzer osint TICKER` in fake mode (osint-research spec: Research CLI command)."""

from __future__ import annotations

import json

import pytest
import respx
from typer.testing import CliRunner

from stock_analyzer.cli import app
from stock_analyzer.companies import TrackedCompany
from stock_analyzer.config import get_settings, reset_settings_cache
from stock_analyzer.osint.models import AREAS
from stock_analyzer.store import get_store


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_FAKE", "true")
    reset_settings_cache()
    get_store(get_settings()).add_tracked(
        TrackedCompany(
            ticker="ELAL", name_he="אל על", name_en="El Al Israel Airlines", fr_company_id=1, source="added"
        )
    )
    yield lambda *args: CliRunner().invoke(app, ["osint", *args])
    reset_settings_cache()


@respx.mock  # no routes: fake mode must make no HTTP request
def test_text_output(cli):
    res = cli("ELAL")
    assert res.exit_code == 0, res.output
    out = res.output
    assert out.startswith("ELAL — אל על / El Al Israel Airlines")
    assert "Overall: WATCH" in out
    for area in AREAS:
        assert f"  {area} (" in out
    assert "Risks:" in out and "Strengths:" in out and "Sources:" in out
    assert "https://news.example.com/osint/" in out
    assert "searches 8/52" in out
    # improve-osint-evidence: profile, key drivers, importance, trend and verdicts
    assert "industry: example industry" in out and "Key drivers:" in out
    assert "importance high" in out and "trend up" in out and "(trend flat: stable)" in out
    assert "supported" in out and "duplicates merged 0" in out and "not supported by source 0" in out


@respx.mock
def test_json_output(cli):
    first = json.loads(cli("ELAL", "--json", "--months", "6").output)
    assert first["ticker"] == "ELAL" and first["window_months"] == 6 and not first["from_cache"]
    assert len(first["scorecard"]["areas"]) == len(AREAS) and first["findings"]
    second = json.loads(cli("ELAL", "--json", "--months", "6").output)
    assert second["from_cache"] is False  # every run is fresh


def test_unknown_ticker(cli):
    res = cli("NOPE")
    assert res.exit_code == 1 and "company_not_found" in res.output
