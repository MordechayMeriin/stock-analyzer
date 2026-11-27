"""`compare` CLI command (report-diff spec: comparison from the CLI)."""

from typer.testing import CliRunner

from stock_analyzer.cli import app
from stock_analyzer.config import Settings, reset_settings_cache
from tests.conftest import seed_business_slices


def test_compare_prints_sections_statuses_and_node_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    reset_settings_cache()
    seed_business_slices(Settings(data_dir=tmp_path))

    result = CliRunner().invoke(app, ["compare", "MLTM", "2023", "2024", "2025"])

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert "FY2023→24" in lines[1] and "FY2024→25" in lines[1]
    marketing = next(line for line in lines if line.startswith("שיווק והפצה"))
    assert marketing.count("unchanged") == 2 and "2023:business-12" in marketing
    legal = next(line for line in lines if line.startswith("הליכים משפטיים"))
    assert legal.count("changed") == 2 and "unchanged" not in legal


def test_compare_needs_two_years(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    reset_settings_cache()
    result = CliRunner().invoke(app, ["compare", "MLTM", "2025"])
    assert result.exit_code == 1 and "two different fiscal years" in result.output
