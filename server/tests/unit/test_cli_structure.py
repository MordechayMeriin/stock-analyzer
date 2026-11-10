from typer.testing import CliRunner

from stock_analyzer.cli import app
from stock_analyzer.config import Settings, reset_settings_cache
from stock_analyzer.ingest.fr_client import Filing, save_report
from tests.conftest import fixture_text


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
