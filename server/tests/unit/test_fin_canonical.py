"""Canonical sheet (canonical-financials spec)."""

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from stock_analyzer.errors import TemplateNotSupported
from stock_analyzer.fin.canonical import TEMPLATES, build_sheet
from stock_analyzer.fin.normalize import FinValue, financials_template, normalize_financials
from tests.conftest import FIXTURES


def load(name: str):
    data = json.loads((FIXTURES / name).read_text())
    return normalize_financials(data), financials_template(data)


@pytest.fixture(scope="module")
def malam():
    values, template = load("mltm_financials.json")
    return build_sheet(values, template)


def fv(
    code: str, value: str, fy: int = 2025, *, at: datetime | None = None, filing: int | None = 1
) -> FinValue:
    return FinValue(
        code=code,
        label=code,
        statement="balance_sheet",
        fiscal_year=fy,
        value=Decimal(value),
        currency="ILS",
        raw_value=None,
        scale=None,
        available_at=at or datetime(2026, 3, 1, tzinfo=UTC),
        source_filing_id=filing,
    )


def test_reported_value_wins(malam):
    cell = malam.cell(2025, "common_equity")
    assert (
        cell.value == Decimal("767184000")
        and cell.basis == "reported"
        and cell.source == "total_common_equity"
    )


def test_derived_when_the_total_is_missing(malam):
    cell = malam.cell(2023, "common_equity")
    assert cell.basis == "derived" and cell.source == "common_from_equity"
    assert cell.value == Decimal("617841000")  # 613,453,000 − (−4,388,000)
    assert cell.embodies == "BS5"


def test_nothing_to_resolve_from(malam):
    cell = malam.cell(2021, "receivables")
    assert cell.value is None and cell.basis == "missing" and cell.source is None


def test_provenance_of_a_derived_cell():
    late = datetime(2026, 5, 1, tzinfo=UTC)
    sheet = build_sheet(
        [fv("total_equity", "100", filing=7), fv("minority_interest", "4", at=late, filing=7)], "industrial"
    )
    cell = sheet.cell(2025, "common_equity")
    assert cell.source == "common_from_equity" and cell.inputs == ["total_equity", "minority_interest"]
    assert cell.available_at == late and cell.source_filing_id == 7


def test_derived_sum_stays_exact():
    sheet = build_sheet(
        [fv("total_common_equity", "0.1"), fv("minority_interest", "0.2")],
        "industrial",
    )
    assert sheet.value(2025, "total_equity") == Decimal("0.3")


def test_derived_from_inputs_of_different_filings_has_no_filing():
    sheet = build_sheet(
        [fv("total_equity", "100", filing=7), fv("minority_interest", "4", filing=8)], "industrial"
    )
    assert sheet.cell(2025, "common_equity").source_filing_id is None


def test_code_sum_and_fallback_code():
    sheet = build_sheet(
        [
            fv("short_term_borrowings", "10"),
            fv("current_portion_of_long_term_debt", "5"),
            fv("long_term_debt", "20"),
        ],
        "industrial",
    )
    current = sheet.cell(2025, "current_debt")
    assert (
        current.value == Decimal("15")
        and current.basis == "derived"
        and current.source == "current_debt_parts"
    )
    noncurrent = sheet.cell(2025, "noncurrent_debt")
    assert noncurrent.basis == "reported" and noncurrent.source == "long_term_debt"
    total = sheet.cell(2025, "total_debt")
    assert total.value == Decimal("35") and total.source == "debt_from_parts" and total.embodies == "BS2"


def test_code_sum_needs_every_part():
    sheet = build_sheet([fv("short_term_borrowings", "10")], "industrial")
    assert sheet.cell(2025, "current_debt").basis == "missing"


def test_mutual_rules_fill_each_other_without_recursing():
    sheet = build_sheet([fv("revenue", "100"), fv("gross_profit", "30")], "industrial")
    assert sheet.value(2025, "cost_of_revenue") == Decimal("70")
    assert sheet.cell(2025, "gross_profit").basis == "reported"
    empty = build_sheet([fv("revenue", "100")], "industrial")
    assert empty.cell(2025, "gross_profit").basis == "missing"
    assert empty.cell(2025, "cost_of_revenue").basis == "missing"


def test_source_filing_type_is_kept():
    values, template = load("lumi_financials.json")
    sheet = build_sheet(values, template)
    assert sheet.cell(2025, "total_assets").source_filing_type == "IR"  # FY2025 from an interim report
    assert sheet.cell(2024, "total_assets").source_filing_type == "10-K"


@pytest.mark.parametrize("template", ["reit", None])
def test_unknown_template(template):
    values, _ = load("mltm_financials.json")
    with pytest.raises(TemplateNotSupported) as info:
        build_sheet(values, template)
    assert (template or "template") in str(info.value)


def test_every_template_field_in_every_year(malam):
    assert all(set(malam.cells[fy]) == set(malam.fields) for fy in malam.years)
    assert malam.fields == [f.name for f in TEMPLATES["industrial"]]


# -- template field sets (task 2.2)


def test_industrial_sheet(malam):
    assert malam.template == "industrial" and malam.years == [2025, 2024, 2023, 2022, 2021]
    for fy in malam.years:
        for name in ("revenue", "gross_profit", "total_assets", "total_equity", "common_equity", "cfo"):
            assert malam.cell(fy, name).value is not None, (fy, name)


def test_bank_sheet():
    values, template = load("lumi_financials.json")
    sheet = build_sheet(values, template)
    assert all(set(sheet.cells[fy]) == set(sheet.fields) for fy in sheet.years)
    assert {"loans_net", "customer_deposits", "cet1_ratio", "tier1_ratio"} <= set(sheet.fields)
    assert "gross_profit" not in sheet.fields and "revenue" not in sheet.fields
    assert sheet.value(2024, "loans_net") == Decimal("455519000000")
    assert sheet.value(2024, "cet1_ratio") == Decimal("0.1198")


def test_insurer_sheet():
    values, template = load("harl_financials.json")
    sheet = build_sheet(values, template)
    assert sheet.years == [2025, 2024, 2023, 2022, 2021, 2020]
    assert "gross_profit" not in sheet.fields and sheet.value(2025, "net_income_parent") == Decimal(
        "2990000000"
    )


def test_debt_fallback_matches_reported_total_on_malam():
    values, template = load("mltm_financials.json")
    reported = build_sheet(values, template)
    stripped = [
        v
        for v in values
        if v.code not in {"total_debt_bs", "total_current_debt_bs", "total_non_current_debt_bs", "net_debt"}
    ]
    derived = build_sheet(stripped, template)
    assert derived.cell(2025, "total_debt").basis == "derived"
    assert derived.value(2025, "current_debt") == reported.value(2025, "current_debt") == Decimal("443208000")
    assert derived.value(2025, "total_debt") == reported.value(2025, "total_debt") == Decimal("684632000")
    assert derived.value(2025, "net_debt") == reported.value(2025, "net_debt") == Decimal("195034000")


# -- point in time (task 2.3)


def test_value_not_yet_available():
    values, template = load("mltm_financials.json")
    fy2025_at = min(v.available_at for v in values if v.fiscal_year == 2025)
    before = build_sheet(values, template, as_of=fy2025_at.date().replace(day=1))
    assert 2025 not in before.years and before.years[0] == 2024
    assert 2025 in build_sheet(values, template, as_of=fy2025_at).years
