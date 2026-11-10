import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from stock_analyzer.errors import CurrencyMismatch, ParseError
from stock_analyzer.fin.normalize import as_of, decimal_str, normalize_financials, normalize_item
from tests.conftest import FIXTURES


@pytest.fixture(scope="module")
def malam():
    return normalize_financials(json.loads((FIXTURES / "mltm_financials.json").read_text()))


def item(**kw):
    base = {
        "code": "revenue",
        "name": "Total Revenues",
        "statement_type": "IS",
        "value": None,
        "raw_value": None,
        "scale": None,
        "currency": "ILS",
        "available_at": "2026-03-12T08:37:03Z",
    }
    return {**base, **kw}


def test_scaled_value_is_exact():
    v = normalize_item(
        item(raw_value="4138004", scale="thousands", value="4138004000.00"),
        fiscal_year=2025,
        statement_type="IS",
        default_currency="ILS",
        source_filing_id=32935334,
    )
    assert v.value == Decimal("4138004000") and isinstance(v.value, Decimal)
    assert v.raw_value == Decimal("4138004") and v.scale == "thousands" and v.as_reported
    assert v.statement == "income" and v.label == "הכנסות" and v.source_filing_id == 32935334
    assert not v.provider_value_differs


def test_no_float_rounding():
    v = normalize_item(
        item(raw_value="0.1", scale="millions"),
        fiscal_year=2025,
        statement_type="IS",
        default_currency="ILS",
        source_filing_id=1,
    )
    assert v.value == Decimal("100000.0")
    v = normalize_item(
        item(value="3.38", code="basic_eps"),
        fiscal_year=2025,
        statement_type="IS",
        default_currency="ILS",
        source_filing_id=1,
    )
    assert v.value == Decimal("3.38") and str(v.value) == "3.38" and not v.as_reported


def test_computed_value_without_raw_and_unknown_scale():
    v = normalize_item(
        item(value="1767801000.00", code="total_liabilities"),
        fiscal_year=2024,
        statement_type="BS",
        default_currency="ILS",
        source_filing_id=1,
    )
    assert v.value == Decimal("1767801000.00") and v.raw_value is None and not v.as_reported
    with pytest.raises(ParseError, match="unknown scale"):
        normalize_item(
            item(raw_value="1", scale="lakhs"),
            fiscal_year=2025,
            statement_type="IS",
            default_currency="ILS",
            source_filing_id=1,
        )


def test_malam_fixture_values(malam):
    rev = {v.fiscal_year: v for v in malam if v.code == "revenue"}
    assert rev[2025].value == Decimal("4138004000") and rev[2024].value == Decimal("3781339000")
    cost = next(v for v in malam if v.code == "cost_of_revenue" and v.fiscal_year == 2025)
    assert (cost.raw_value, cost.scale, cost.value) == (
        Decimal("3704618"),
        "thousands",
        Decimal("3704618000"),
    )
    statements = {v.statement for v in malam}
    assert statements == {"income", "balance_sheet", "cash_flow", "supplemental"}
    assert {v.currency for v in malam} == {"ILS"}


def test_currency_mismatch_names_both(malam):
    data = json.loads((FIXTURES / "mltm_financials.json").read_text())
    p2025 = next(p for p in data["periods"] if p["fiscal_year"] == 2025)
    for st in p2025["statements"]:
        for li in st["line_items"]:
            li["currency"] = "USD"
    with pytest.raises(CurrencyMismatch) as info:
        normalize_financials(data)
    assert "ILS" in str(info.value) and "USD" in str(info.value) and "FY2025 revenue" in str(info.value)


def test_late_availability_trap(malam):
    fy2023 = [v for v in malam if v.fiscal_year == 2023]
    assert fy2023 and {v.available_at for v in fy2023} == {
        datetime(2024, 6, 13, 17, 12, 12, 860000, tzinfo=UTC)
    }
    early = as_of(malam, date(2024, 4, 1))  # after the March report, before the June iXBRL
    assert not [v for v in early if v.fiscal_year == 2023]
    later = as_of(malam, date(2024, 6, 13))  # end of that day includes it
    assert [v for v in later if v.fiscal_year == 2023]
    assert not [v for v in later if v.fiscal_year == 2024]


def test_item_without_value_is_skipped():
    assert (
        normalize_item(
            item(code="shares_outstanding_basic"),
            fiscal_year=2025,
            statement_type="IS",
            default_currency="ILS",
            source_filing_id=1,
        )
        is None
    )


def test_as_of_excludes_unknown_availability():
    v = normalize_item(
        item(value="1", available_at=None),
        fiscal_year=2025,
        statement_type="IS",
        default_currency="ILS",
        source_filing_id=1,
    )
    assert as_of([v], date(2030, 1, 1)) == []


def test_decimal_str_canonical():
    assert decimal_str(Decimal("4138004000.000000")) == "4138004000"
    assert decimal_str(Decimal("3.380000")) == "3.38"
    assert decimal_str(Decimal("-109210000.00")) == "-109210000"
    assert decimal_str(Decimal("1E+9")) == "1000000000"
    assert decimal_str(Decimal("0.0001")) == "0.0001"
