import uuid

import psycopg
import pytest
from typer.testing import CliRunner

from stock_analyzer.cli import app
from stock_analyzer.config import Settings, reset_settings_cache
from stock_analyzer.ingest.fr_client import Filing, save_report
from tests.conftest import TEST_DATABASE_URL, fixture_text


def seed(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    reset_settings_cache()
    filing = Filing(
        id=32935334,
        title="Periodic and annual report for 2025",
        fiscal_year=2025,
        document="https://cdn.example/r.pdf",
    )
    save_report(Settings(data_dir=tmp_path), "MLTM", 2025, filing, fixture_text("mltm_2025_style_b.md"))


def test_structure_prints_tree_and_coverage(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    result = CliRunner().invoke(app, ["structure", "MLTM", "2025"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "תיאור עסקי התאגיד  [p" in out and "#business" in out
    assert "22 דיון בגורמי סיכון  [p" in out and "#business-22" in out
    assert "  22.1 גורמי סיכון חיצוניים" in out  # nested with indentation
    assert "MLTM FY2025 — filing 32935334, 36 pages (style B)" in out
    assert "chapters: business, directors, financials, additional, governance" in out
    assert "warning: only" in out  # the fixture holds fewer than 10 business sections


def test_structure_not_cached_in_cached_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    reset_settings_cache()
    result = CliRunner().invoke(app, ["structure", "MLTM", "2024"])
    assert result.exit_code == 1 and "not_cached" in result.output and "fetch MLTM 2024" in result.output


def test_structure_unknown_ticker(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    result = CliRunner().invoke(app, ["structure", "NOPE", "2025"])
    assert result.exit_code == 1 and "company_not_found" in result.output


def test_db_init_needs_database_url(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    reset_settings_cache()
    result = CliRunner().invoke(app, ["db", "init"])
    assert result.exit_code == 1
    assert "DATABASE_URL is not set" in result.output


@pytest.mark.skipif(TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not set")
def test_db_init_creates_then_reports_present(monkeypatch):
    from stock_analyzer import store as store_module
    from stock_analyzer.store.pg import PgStore

    schema = f"sa_test_{uuid.uuid4().hex[:12]}"
    pg = PgStore(TEST_DATABASE_URL, schema=schema)
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setattr(store_module, "get_store", lambda settings, **_: pg)
    reset_settings_cache()
    try:
        first = CliRunner().invoke(app, ["db", "init"])
        assert first.exit_code == 0, first.output
        assert f"created schema '{schema}'" in first.output
        second = CliRunner().invoke(app, ["db", "init"])
        assert second.exit_code == 0 and "already present" in second.output
        assert TEST_DATABASE_URL not in first.output + second.output
    finally:
        pg.shutdown()
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
            conn.execute(f'drop schema if exists "{schema}" cascade')


# ---------------------------------------------------------------- parse-check (coverage scorecard)


def _save(tmp_path, ticker: str, year: int, text: str, filing_id: int = 1) -> None:
    filing = Filing(id=filing_id, title=f"Periodic and annual report for {year}", fiscal_year=year)
    save_report(Settings(data_dir=tmp_path), ticker, year, filing, text)


def test_parse_check_rows_for_every_stored_report(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)  # MLTM FY2025 fixture: all five chapters
    _save(tmp_path, "ELAL", 2025, "פתיחה\n\n---\n\nטקסט ללא פרקים\n")  # style B, no chapters at all
    result = CliRunner().invoke(app, ["parse-check"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0].startswith("TICKER") and "MISSING / ERROR" in lines[0]
    elal = next(ln for ln in lines if ln.startswith("ELAL"))
    mltm = next(ln for ln in lines if ln.startswith("MLTM"))
    assert lines.index(elal) < lines.index(mltm)  # sorted by ticker
    assert " 5/5 " in mltm and "missing" not in mltm
    assert " 0/5 " in elal
    assert "missing: business, directors, financials, additional, governance" in elal


def test_parse_check_filters_by_ticker_and_year(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    _save(tmp_path, "ELAL", 2025, "א\n\n---\n\nב\n")
    result = CliRunner().invoke(app, ["parse-check", "mltm", "2025"])
    assert result.exit_code == 0, result.output
    assert any(ln.startswith("MLTM   2025") for ln in result.output.splitlines())
    assert "ELAL" not in result.output


def test_parse_check_error_row_and_exit_code(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    _save(tmp_path, "BAD", 2025, "no page markers and no page rules at all\n")  # no page style → ParseError
    result = CliRunner().invoke(app, ["parse-check"])
    assert result.exit_code == 1
    bad = next(ln for ln in result.output.splitlines() if ln.startswith("BAD"))
    assert "ERROR ParseError: unknown page style" in bad
    assert any(
        ln.startswith("MLTM") and "5/5" in ln for ln in result.output.splitlines()
    )  # others still printed


def test_parse_check_nothing_stored(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    reset_settings_cache()
    result = CliRunner().invoke(app, ["parse-check"])
    assert result.exit_code == 0 and "no stored reports" in result.output
