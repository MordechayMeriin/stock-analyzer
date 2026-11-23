"""`stock-analyzer companies list | add | remove` on the file backend."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from stock_analyzer.cli import app
from stock_analyzer.config import reset_settings_cache


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    reset_settings_cache()
    yield lambda *args: CliRunner().invoke(app, ["companies", *args])
    reset_settings_cache()


def test_add_list_remove(cli, tmp_path):
    r = cli("add", "--fr-id", "1234", "--ticker", "abc", "--name-he", "חברה לדוגמה", "--name-en", "Example")
    assert r.exit_code == 0, r.output
    assert "now tracking ABC" in r.output
    assert (tmp_path / "companies_added.json").exists()

    r = cli("list")
    assert r.exit_code == 0, r.output
    lines = r.output.splitlines()
    assert lines[0].split()[:3] == ["MLTM", "6901", "registry"]
    assert lines[1].split()[:3] == ["ABC", "1234", "added"]

    r = cli("remove", "abc")
    assert r.exit_code == 0 and "stopped tracking ABC" in r.output
    assert [line.split()[0] for line in cli("list").output.splitlines()] == ["MLTM"]


def test_refusals_are_clear(cli, monkeypatch):
    r = cli("add", "--fr-id", "6901", "--ticker", "MALAM", "--name-he", "מלם")
    assert r.exit_code == 1 and "company_already_tracked" in r.output and "MLTM" in r.output
    r = cli("add", "--fr-id", "1", "--ticker", "A B", "--name-he", "x")
    assert r.exit_code == 1 and "validation_error" in r.output and "ticker" in r.output
    r = cli("remove", "MLTM")
    assert r.exit_code == 1 and "company_not_removable" in r.output


def test_cached_only_server_explains(cli, monkeypatch):
    monkeypatch.setenv("ALLOW_LIVE", "false")
    reset_settings_cache()
    r = cli("add", "--fr-id", "1234", "--ticker", "ABC", "--name-he", "חברה")
    assert r.exit_code == 1
    assert "live_disabled" in r.output and "ALLOW_LIVE" in r.output
