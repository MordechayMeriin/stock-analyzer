"""Core ratios, changes and confidence (financial-analysis spec)."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from stock_analyzer.config import Settings
from stock_analyzer.fin.checks import run_checks
from stock_analyzer.fin.normalize import FinValue, normalize_financials
from stock_analyzer.fin.ratios import RATIOS, change_value, compute_changes, compute_ratios
from tests.conftest import FIXTURES

TOL = Settings().check_tolerances


@pytest.fixture(scope="module")
def malam() -> list[FinValue]:
    return normalize_financials(json.loads((FIXTURES / "mltm_financials.json").read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def malam_ratios(malam):
    checks = run_checks(malam, TOL)
    return {(r.code, r.fiscal_year): r for r in compute_ratios(malam, checks)}, checks


def fv(code: str, value: str | int, year: int = 2025, statement: str = "income") -> FinValue:
    return FinValue(
        code=code,
        label=code,
        statement=statement,
        fiscal_year=year,
        value=Decimal(value),
        currency="ILS",
        raw_value=None,
        scale=None,
        available_at=None,
        source_filing_id=None,
    )


def pct(value: str, places: int = 2) -> Decimal:
    return round(Decimal(value) * 100, places)


def test_malam_fy2025_core_ratios(malam_ratios):
    r, _ = malam_ratios

    def val(code: str) -> str:
        return r[(code, 2025)].value

    assert pct(val("gross_margin")) == Decimal("10.47")
    assert pct(val("operating_margin")) == Decimal("5.30")
    assert pct(val("ebitda_margin")) == Decimal("7.91")
    assert pct(val("net_margin")) == Decimal("1.79")
    assert round(Decimal(val("current_ratio")), 2) == Decimal("1.18")
    assert round(Decimal(val("cash_ratio")), 2) == Decimal("0.37")
    assert round(Decimal(val("debt_to_equity")), 2) == Decimal("0.90")
    assert round(Decimal(val("net_debt_to_ebitda")), 2) == Decimal("0.60")
    assert pct(val("equity_to_assets"), 1) == Decimal("29.0")
    assert pct(val("short_term_debt_share"), 1) == Decimal("64.7")
    assert round(Decimal(val("free_cash_flow")) / 1_000_000, 1) == Decimal("65.5")
    assert pct(val("free_cash_flow_margin")) == Decimal("1.58")


def test_every_ratio_records_its_inputs(malam_ratios):
    r, _ = malam_ratios
    fcf = r[("free_cash_flow", 2025)]
    assert fcf.inputs == {"cash_from_operations": "174728000", "capital_expenditure_cf": "-109210000"}
    assert fcf.value == "65518000"  # capex is negative, so FCF = CFO + capex
    assert {r.code for r in RATIOS} == {code for code, year in r if year == 2025}


def test_values_are_exact_decimals_not_floats(malam_ratios):
    r, _ = malam_ratios
    for ratio in r.values():
        assert ratio.value is None or "e" not in ratio.value.lower()


def test_missing_input_has_no_value_with_reason():
    ratios = compute_ratios([fv("revenue", 100), fv("net_debt", 50)], [])
    by = {x.code: x for x in ratios}
    assert by["ebitda_margin"].value is None and "ebitda" in by["ebitda_margin"].reason
    assert by["net_debt_to_ebitda"].value is None and "ebitda" in by["net_debt_to_ebitda"].reason


def test_zero_denominator_has_no_value_with_reason():
    ratios = compute_ratios([fv("total_current_assets", 100), fv("total_current_liabilities", 0)], [])
    (current,) = [x for x in ratios if x.code == "current_ratio"]
    assert current.value is None and "zero" in current.reason


def test_negative_equity_base_is_not_meaningful():
    ratios = compute_ratios([fv("total_debt_bs", 100), fv("total_equity", -20)], [])
    (de,) = [x for x in ratios if x.code == "debt_to_equity"]
    assert de.value is None and "negative" in de.reason


def test_malam_revenue_change(malam, malam_ratios):
    r, checks = malam_ratios
    changes = compute_changes(malam, r.values(), checks)
    (rev,) = [c for c in changes if c.kind == "FIN" and c.code == "revenue" and c.to_year == 2025]
    assert rev.from_year == 2024 and rev.unit == "percent"
    assert round(Decimal(rev.value) * 100, 2) == Decimal("9.43")
    assert rev.old == "3781339000" and rev.new == "4138004000"


def test_margin_change_is_in_points():
    values = [
        fv("gross_profit", "10.60", 2024),
        fv("revenue", "100", 2024),
        fv("gross_profit", "10.47", 2025),
        fv("revenue", "100", 2025),
    ]
    ratios = compute_ratios(values, [])
    (gm,) = [c for c in compute_changes(values, ratios, []) if c.kind == "RATIO" and c.code == "gross_margin"]
    assert gm.unit == "pp"
    assert round(Decimal(gm.value) * 100, 2) == Decimal("-0.13")


def test_change_rules():
    assert change_value(Decimal(-100), Decimal(50), "percent") == (None, "the sign changed between the years")
    assert change_value(Decimal(0), Decimal(50), "percent") == (None, "the previous value is zero")
    assert change_value(None, Decimal(50), "percent")[0] is None
    assert change_value(Decimal(-100), Decimal(-150), "percent")[0] == Decimal("-0.5")  # a loss deepens
    assert change_value(Decimal(100), Decimal(0), "percent")[0] == Decimal(-1)
    assert change_value(Decimal(0), Decimal("0.05"), "pp")[0] == Decimal(
        "0.05"
    )  # margin from zero: +5 points
    assert change_value(Decimal("1.2"), Decimal("0.9"), "multiple")[0] == Decimal("-0.3")


def test_net_income_sign_change_has_no_value():
    values = [fv("net_income_loss", -10, 2024), fv("net_income_loss", 20, 2025)]
    (ni,) = [c for c in compute_changes(values, [], []) if c.code == "net_income_loss"]
    assert ni.value is None and "sign" in ni.reason


def test_free_cash_flow_is_low_confidence_on_cf1(malam_ratios):
    r, _ = malam_ratios
    for code in ("free_cash_flow", "free_cash_flow_margin"):
        assert r[(code, 2025)].confidence == "low"
        assert "CF1" in r[(code, 2025)].failed_checks


def test_gross_margin_is_high_confidence(malam_ratios):
    r, _ = malam_ratios
    gm = r[("gross_margin", 2025)]
    assert gm.confidence == "high" and gm.failed_checks == []


def test_change_confidence_takes_both_years(malam, malam_ratios):
    r, checks = malam_ratios
    changes = compute_changes(malam, r.values(), checks)
    (fcf,) = [c for c in changes if c.kind == "RATIO" and c.code == "free_cash_flow" and c.to_year == 2025]
    assert fcf.confidence == "low" and "CF1" in fcf.failed_checks
    (fcf_prev,) = [
        c for c in changes if c.kind == "RATIO" and c.code == "free_cash_flow" and c.to_year == 2024
    ]
    assert fcf_prev.confidence == "high"
