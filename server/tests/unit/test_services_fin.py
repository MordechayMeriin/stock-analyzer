from datetime import date

from typer.testing import CliRunner

from stock_analyzer.cli import app
from stock_analyzer.config import reset_settings_cache
from stock_analyzer.services import financials as fin_service
from stock_analyzer.services.context import Ctx
from tests.conftest import seed_malam


def test_financials_grouped_by_statement_and_year(settings):
    seed_malam(settings)
    out = fin_service.financials(Ctx(settings), "MLTM")
    assert out.currency == "ILS" and out.years == [2025, 2024, 2023, 2022, 2021]
    assert [s.statement for s in out.statements] == ["income", "balance_sheet", "cash_flow", "supplemental"]
    income = next(s for s in out.statements if s.statement == "income")
    revenue = next(i for i in income.items if i.code == "revenue")
    assert revenue.label == "הכנסות" and revenue.values["2025"] == "4138004000"
    assert all(isinstance(v, str) or v is None for i in income.items for v in i.values.values())
    assert out.available_at["2023"].startswith("2024-06-13")


def test_financials_as_of_excludes_late_values(settings):
    seed_malam(settings)
    out = fin_service.financials(Ctx(settings), "MLTM", as_of=date(2024, 4, 1))
    assert 2023 not in out.years and out.years[0] == 2022 and out.as_of == "2024-04-01"


def test_fin_raw_cli_shows_fy2025_revenue(settings, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(settings.data_dir))
    reset_settings_cache()
    seed_malam(settings)
    result = CliRunner().invoke(app, ["fin-raw", "MLTM"])
    assert result.exit_code == 0, result.output
    assert "currency ILS" in result.output and "דוח רווח והפסד (income)" in result.output
    revenue_line = next(line for line in result.output.splitlines() if line.startswith("הכנסות"))
    assert "4,138,004,000" in revenue_line and "FY2025" in result.output


def test_fin_raw_not_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    reset_settings_cache()
    result = CliRunner().invoke(app, ["fin-raw", "MLTM"])
    assert result.exit_code == 1 and "not_cached" in result.output
