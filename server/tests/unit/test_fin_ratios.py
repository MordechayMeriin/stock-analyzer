"""Ratio registry and engine (financial-ratios spec)."""

import json
from decimal import Decimal

import pytest

from stock_analyzer.fin.canonical import build_sheet
from stock_analyzer.fin.checks import run_checks
from stock_analyzer.fin.normalize import financials_template, normalize_financials
from stock_analyzer.fin.ratios import RATIO_BY_CODE, RATIOS, change, compute, div, growth, ratios_for
from tests.conftest import FIXTURES

Q = Decimal("0.0001")


def series_for(name: str) -> dict[str, object]:
    data = json.loads((FIXTURES / name).read_text())
    sheet = build_sheet(normalize_financials(data), financials_template(data))
    return {s.code: s for s in compute(sheet, run_checks(sheet))}


@pytest.fixture(scope="module")
def malam():
    return series_for("mltm_financials.json")


@pytest.fixture(scope="module")
def leumi():
    return series_for("lumi_financials.json")


@pytest.fixture(scope="module")
def harel():
    return series_for("harl_financials.json")


# -- task 4.1: arithmetic, averages, missing values, confidence, change


def test_malam_gross_margin(malam):
    v = malam["gross_margin"].values[2025]
    assert v.value.quantize(Q) == Decimal("0.1047") and v.basis == "computed"
    assert v.inputs == {"gross_profit": Decimal("433386000"), "revenue": Decimal("4138004000")}


def test_roe_with_an_average(malam):
    v = malam["roe"].values[2025]
    assert v.avg_used and v.value.quantize(Q) == Decimal("0.1003")
    assert set(v.inputs) == {"net_income_parent", "common_equity", "opening:common_equity"}


def test_oldest_year_uses_the_closing_balance(malam):
    v = malam["roe"].values[2021]
    assert v.value is not None and not v.avg_used and "opening:common_equity" not in v.inputs


def test_missing_input_names_it(malam):
    v = malam["quick_ratio"].values[2021]
    assert v.value is None and "receivables" in v.missing_reason
    assert "לקוחות וחייבים" in v.missing_message_he


def test_no_prior_year_for_growth(malam):
    v = malam["revenue_growth"].values[2021]
    assert v.value is None and v.missing_reason == "no_prior_year" and v.status == "na"


def test_failed_equity_check_lowers_confidence(malam):
    v = malam["roe"].values[2025]
    assert v.confidence == "low" and "BS5" in v.failed_checks
    assert malam["gross_margin"].values[2025].confidence == "high"


def test_derived_input_lowers_confidence(malam):
    v = malam["roe"].values[2024]
    assert v.confidence == "low" and "common_equity:2023" in v.derived_inputs


def test_missing_values_carry_no_confidence_flags(leumi):
    v = leumi["npl_ratio"].values[2024]
    assert v.value is None and v.confidence == "high" and v.failed_checks == [] and v.derived_inputs == []


def test_change_beyond_the_threshold():
    gross = RATIO_BY_CODE["gross_margin"]
    assert change(gross, Decimal("0.10"), Decimal("0.11")) == (Decimal("-0.01"), "deteriorated")
    assert change(gross, Decimal("0.12"), Decimal("0.11"))[1] == "improved"
    assert change(gross, Decimal("0.1047"), Decimal("0.1060"))[1] == "stable"
    assert change(RATIO_BY_CODE["debt_to_equity"], Decimal("1.2"), Decimal("1.0"))[1] == "deteriorated"
    assert change(RATIO_BY_CODE["loans_to_deposits"], Decimal("0.80"), Decimal("0.70"))[1] == "changed"
    assert change(gross, None, Decimal("0.1")) == (None, "na")


def test_amount_change_is_relative():
    fcf = RATIO_BY_CODE["free_cash_flow"]
    assert change(fcf, Decimal(110), Decimal(100)) == (Decimal("0.1"), "improved")
    assert change(fcf, Decimal(105), Decimal(100))[1] == "stable"


def test_denominator_reasons():
    from stock_analyzer.fin.ratios import Uncomputable

    with pytest.raises(Uncomputable, match="zero_denominator"):
        div(Decimal(1), Decimal(0))
    with pytest.raises(Uncomputable, match="negative_denominator"):
        div(Decimal(1), Decimal(-2), positive=True)
    with pytest.raises(Uncomputable, match="negative_denominator"):
        growth(Decimal(5), Decimal(-1))
    assert div(Decimal(1), Decimal(-2)) == Decimal("-0.5")


def test_values_are_exact_decimals(malam):
    assert all(
        isinstance(v.value, Decimal) for s in malam.values() for v in s.values.values() if v.value is not None
    )


# -- task 4.2: registry and templates


def test_registry_entry():
    gross = RATIO_BY_CODE["gross_margin"]
    assert (gross.name_he, gross.group, gross.unit, gross.direction) == (
        "שיעור רווח גולמי",
        "profitability",
        "percent",
        "higher",
    )
    assert gross.threshold == Decimal("0.005") and gross.templates == frozenset({"industrial"})


def test_each_template_gets_exactly_its_ratios():
    core = {"roe", "roa", "equity_to_assets", "net_income_growth", "eps_growth", "cfo_to_net_income"}
    industrial = core | {
        "gross_margin", "operating_margin", "ebitda_margin", "net_margin", "revenue_growth",
        "current_ratio", "quick_ratio", "debt_to_equity", "free_cash_flow", "fcf_margin",
    }  # fmt: skip
    bank = core | {"loans_to_deposits", "npl_ratio", "loan_loss_coverage"} | {
        "cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio",
    }  # fmt: skip
    assert {r.code for r in ratios_for("industrial")} == industrial
    assert {r.code for r in ratios_for("bank")} == bank
    assert {r.code for r in ratios_for("insurer")} == core
    assert len({r.code for r in RATIOS}) == len(RATIOS)


def test_insurer_ratios(harel):
    assert "roe" in harel and "gross_margin" not in harel and "net_margin" not in harel
    v = harel["roe"].values[2021]
    assert v.avg_used and "opening:common_equity" in v.inputs  # FY2021 averages with FY2020


def test_bank_ratios(leumi):
    assert leumi["loans_to_deposits"].values[2024].value.quantize(Q) == Decimal("0.7367")
    assert "gross_margin" not in leumi


def test_cet1_passes_through(leumi):
    v = leumi["cet1_ratio"].values[2024]
    assert v.value == Decimal("0.1198") and v.basis == "reported"


# -- task 4.3: calibration on Malam


def test_malam_series(malam):
    gross = malam["gross_margin"].values
    assert sorted(gross) == [2021, 2022, 2023, 2024, 2025] and all(
        v.value is not None for v in gross.values()
    )
    assert gross[2024].value.quantize(Q) == Decimal("0.1060") and gross[2025].status == "stable"
    assert gross[2024].status == "deteriorated"  # 11.24% → 10.60%


def test_thresholds_give_a_mix_of_statuses(malam):
    statuses = [
        v.status for s in malam.values() for fy, v in s.values.items() if fy >= 2022 and v.status != "na"
    ]
    assert {"stable", "improved", "deteriorated"} <= set(statuses)
    assert max(statuses.count(s) for s in set(statuses)) < 0.6 * len(statuses)


def test_non_annual_source_note(malam, leumi):
    assert leumi["equity_to_assets"].values[2025].notes == [
        "non_annual_source"
    ]  # FY2025 from an interim report
    assert leumi["equity_to_assets"].values[2024].notes == []
    assert malam["gross_margin"].values[2023].notes == []  # annual report filed under the generic RNS type
