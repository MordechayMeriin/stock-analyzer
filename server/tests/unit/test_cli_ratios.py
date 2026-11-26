"""`ratios` CLI command (financial-analysis spec: analysis from the CLI)."""

from typer.testing import CliRunner

from stock_analyzer.cli import app
from stock_analyzer.config import Settings, reset_settings_cache
from tests.conftest import seed_malam


def test_ratios_prints_values_confidence_and_failed_checks(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    reset_settings_cache()
    seed_malam(Settings(data_dir=tmp_path))

    result = CliRunner().invoke(app, ["ratios", "MLTM"])

    assert result.exit_code == 0, result.output
    out = result.output
    gross = next(line for line in out.splitlines() if line.startswith("gross_margin"))
    assert "10.47%" in gross and "10.47% *" not in gross  # high confidence
    fcf = next(line for line in out.splitlines() if line.startswith("free_cash_flow "))
    assert "65.5M *" in fcf  # low confidence: CF1 / CF2
    assert "changes FY2024 → FY2025" in out
    assert "FY2025 CF1:" in out and "FY2025 BS5:" in out
    assert "FY2025 IS1:" not in out  # passed checks are not listed as failures


def test_ratios_not_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    reset_settings_cache()
    result = CliRunner().invoke(app, ["ratios", "MLTM"])
    assert result.exit_code == 1 and "not_cached" in result.output
