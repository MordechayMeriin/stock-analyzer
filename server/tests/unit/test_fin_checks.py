"""Data-quality checks (financial-analysis spec, plan.md §3.2)."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from stock_analyzer.config import Settings
from stock_analyzer.fin.checks import CHECK_IDS, failed_checks_for, run_checks
from stock_analyzer.fin.normalize import FinValue, normalize_financials
from tests.conftest import FIXTURES

TOL = Settings().check_tolerances


@pytest.fixture(scope="module")
def malam() -> list[FinValue]:
    return normalize_financials(json.loads((FIXTURES / "mltm_financials.json").read_text(encoding="utf-8")))


def fv(code: str, value: str | int, year: int = 2025) -> FinValue:
    return FinValue(
        code=code,
        label=code,
        statement="income",
        fiscal_year=year,
        value=Decimal(value),
        currency="ILS",
        raw_value=None,
        scale=None,
        available_at=None,
        source_filing_id=None,
    )


def one(check_id: str, **values) -> str:
    (result,) = [r for r in run_checks([fv(c, x) for c, x in values.items()], TOL) if r.check_id == check_id]
    return result.status


def test_malam_fy2025_fails_exactly_the_expected_checks(malam):
    fy2025 = [r for r in run_checks(malam, TOL) if r.fiscal_year == 2025]
    assert [r.check_id for r in fy2025] == list(CHECK_IDS)
    assert {r.check_id for r in fy2025 if r.status == "fail"} == {"CF1", "CF2", "IS3", "BS4", "BS5"}
    assert {r.check_id for r in fy2025 if r.status == "pass"} == {"BS1", "BS2", "BS3", "IS1", "IS2"}


def test_malam_fy2024_is_consistent_where_data_exists(malam):
    fy2024 = {r.check_id: r.status for r in run_checks(malam, TOL) if r.fiscal_year == 2024}
    assert fy2024["CF1"] == "pass" and fy2024["BS4"] == "pass" and fy2024["BS5"] == "pass"
    assert fy2024["IS3"] == "not_run"  # no net interest expense before FY2025
    assert fy2024["BS2"] == "not_run"  # no debt breakdown before FY2025


def test_failure_detail(malam):
    (cf1,) = [r for r in run_checks(malam, TOL) if r.fiscal_year == 2025 and r.check_id == "CF1"]
    assert cf1.status == "fail"
    assert cf1.inputs["cash_from_operations"] == "174728000"
    assert cf1.expected == "3798000"  # the change in cash
    assert cf1.actual == "38856000"  # CFO + CFI + CFF
    assert cf1.tolerance == "0.02"
    assert cf1.missing == []


def test_missing_input_is_not_run_not_passed():
    status = one("BS1", total_assets=100, total_liabilities=60)
    assert status == "not_run"
    (r,) = [r for r in run_checks([fv("total_assets", 100)], TOL) if r.check_id == "BS1"]
    assert r.missing == ["total_liabilities", "total_equity"] and r.expected is None


@pytest.mark.parametrize(
    ("check_id", "good", "bad"),
    [
        (
            "BS1",
            {"total_assets": 100, "total_liabilities": 60, "total_equity": 40},
            {"total_assets": 100, "total_liabilities": 60, "total_equity": 30},
        ),
        (
            "BS2",
            {"total_debt_bs": 100, "total_current_debt_bs": 30, "total_non_current_debt_bs": 70},
            {"total_debt_bs": 100, "total_current_debt_bs": 30, "total_non_current_debt_bs": 50},
        ),
        (
            "BS3",
            {"net_debt": 60, "total_debt_bs": 100, "total_cash_and_short_term_investments": 40},
            {"net_debt": 90, "total_debt_bs": 100, "total_cash_and_short_term_investments": 40},
        ),
        (
            "BS4",
            {
                "total_current_assets": 100,
                "cash_and_equivalents": 30,
                "total_receivables": 50,
                "inventory": 10,
            },
            {
                "total_current_assets": 100,
                "cash_and_equivalents": 30,
                "total_receivables": 10,
                "inventory": 5,
            },
        ),
        (
            "BS5",
            {"total_equity": 105, "total_common_equity": 100, "minority_interest": 5},
            {"total_equity": 95, "total_common_equity": 100, "minority_interest": 5},
        ),
        (
            "IS1",
            {"gross_profit": 40, "revenue": 100, "cost_of_revenue": 60},
            {"gross_profit": 45, "revenue": 100, "cost_of_revenue": 60},
        ),
        (
            "IS2",
            {"net_income_loss": 90, "consolidated_net_income": 100, "minority_interest_in_earnings": 10},
            {"net_income_loss": 100, "consolidated_net_income": 100, "minority_interest_in_earnings": 10},
        ),
        (
            "IS3",
            {
                "operating_income_loss": 100,
                "net_interest_expense": 20,
                "earnings_before_tax_including_unusual_items": 78,
            },
            {
                "operating_income_loss": 100,
                "net_interest_expense": 20,
                "earnings_before_tax_including_unusual_items": 50,
            },
        ),
        (
            "CF1",
            {
                "cash_from_operations": 100,
                "cash_from_investing": -40,
                "cash_from_financing": -30,
                "net_change_in_cash_cf": 30,
            },
            {
                "cash_from_operations": 100,
                "cash_from_investing": -40,
                "cash_from_financing": -30,
                "net_change_in_cash_cf": 5,
            },
        ),
        (
            "CF2",
            {"cash_from_investing": -50, "capital_expenditure_cf": -30, "cash_acquisitions_cf": -20},
            {"cash_from_investing": -30, "capital_expenditure_cf": -30, "cash_acquisitions_cf": -20},
        ),
    ],
)
def test_each_check_passes_and_fails(check_id, good, bad):
    assert one(check_id, **good) == "pass"
    assert one(check_id, **bad) == "fail"


def test_bs4_fails_when_parts_exceed_the_total():
    assert one("BS4", total_current_assets=100, cash_and_equivalents=80, total_receivables=40) == "fail"


def test_cf2_passes_when_capex_is_the_only_investing_item():
    assert one("CF2", cash_from_investing=-30, capital_expenditure_cf=-30) == "pass"
    assert one("CF2", cash_from_investing=-30, capital_expenditure_cf=-30, cash_acquisitions_cf=0) == "pass"


def test_failed_checks_for_matches_inputs_and_year(malam):
    results = run_checks(malam, TOL)
    assert set(failed_checks_for(["cash_from_operations"], 2025, results)) == {"CF1"}
    assert set(failed_checks_for(["capital_expenditure_cf"], 2025, results)) == {"CF2"}
    assert failed_checks_for(["revenue", "gross_profit"], 2025, results) == []
    assert failed_checks_for(["cash_from_operations"], 2024, results) == []
