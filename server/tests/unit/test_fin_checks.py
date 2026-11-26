"""Data-quality checks (canonical-financials spec: Data-quality checks)."""

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from stock_analyzer.fin.canonical import Code, build_sheet, field_def
from stock_analyzer.fin.checks import CHECKS, failed_by_cell, run_checks
from stock_analyzer.fin.normalize import FinValue, financials_template, normalize_financials
from tests.conftest import FIXTURES


def results_for(name: str) -> dict[int, dict[str, object]]:
    data = json.loads((FIXTURES / name).read_text())
    sheet = build_sheet(normalize_financials(data), financials_template(data))
    return {fy: {r.id: r for r in rs} for fy, rs in run_checks(sheet).items()}


@pytest.fixture(scope="module")
def malam():
    return results_for("mltm_financials.json")


def reported(template: str, values: dict[str, Decimal]) -> list[FinValue]:
    """FinValues under each field's own provider code (its first Code source)."""
    out = []
    for name, value in values.items():
        code = next(s.code for s in field_def(template, name).sources if isinstance(s, Code))
        out.append(
            FinValue(
                code=code,
                label=code,
                statement="balance_sheet",
                fiscal_year=2025,
                value=value,
                currency="ILS",
                raw_value=None,
                scale=None,
                available_at=datetime(2026, 3, 1, tzinfo=UTC),
                source_filing_id=1,
            )
        )
    return out


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.id)
@pytest.mark.parametrize("off_by", [Decimal(0), Decimal(100_000)])
def test_each_check_passes_and_fails(check, off_by):
    template = sorted(check.templates)[0]
    inputs = {name: Decimal(1_000_000 * (i + 2)) for i, name in enumerate(check.inputs)}
    left = check.right(*inputs.values()) + off_by
    sheet = build_sheet(reported(template, {check.left: left, **inputs}), template)
    result = next(r for r in run_checks(sheet)[2025] if r.id == check.id)
    assert result.status == ("passed" if off_by == 0 else "failed")
    if off_by:
        assert result.difference == off_by and result.left == left and result.right == left - off_by


def test_tolerance_absorbs_rounding():
    check = next(c for c in CHECKS if c.id == "BS1")
    sheet = build_sheet(
        reported(
            "industrial",
            {
                "total_assets": Decimal(1_000_400),
                "total_liabilities": Decimal(600_000),
                "total_equity": Decimal(400_000),
            },
        ),
        "industrial",
    )
    assert next(r for r in run_checks(sheet)[2025] if r.id == check.id).status == "passed"


def test_cash_flow_identity_fails(malam):
    cf1 = malam[2025]["CF1"]
    assert cf1.status == "failed"
    assert cf1.right == Decimal("38856000") and cf1.left == Decimal("3798000")
    assert cf1.difference == Decimal("-35058000")


def test_equity_identity_fails(malam):
    bs5 = malam[2025]["BS5"]
    assert bs5.status == "failed" and bs5.left == Decimal("762392000") and bs5.right == Decimal("771976000")


def test_balance_sheet_balances(malam):
    assert malam[2025]["BS1"].status == "passed"


def test_failed_cells_point_at_their_checks(malam):
    data = json.loads((FIXTURES / "mltm_financials.json").read_text())
    sheet = build_sheet(normalize_financials(data), financials_template(data))
    by_cell = failed_by_cell(run_checks(sheet)[2025])
    assert by_cell["common_equity"] == ["BS5"] and by_cell["cfo"] == ["CF1"]


def test_bank_and_insurer_identities_hold():
    leumi = results_for("lumi_financials.json")[2024]
    assert leumi["BS1"].status == "passed" and leumi["BS5"].status == "passed"
    assert leumi["IS2"].status == "not_applicable"  # FY2024 income statement has net income only
    assert "BS2" not in leumi and "CF1" not in leumi  # industrial-only checks
    harel = results_for("harl_financials.json")[2025]
    assert {harel[c].status for c in ("BS1", "BS5", "IS2")} == {"passed"}


# -- task 3.2


def test_derived_common_equity_makes_its_check_not_applicable(malam):
    bs5 = malam[2023]["BS5"]
    assert bs5.status == "not_applicable" and "common_equity" in (bs5.reason or "")


def test_missing_cell_makes_check_not_applicable(malam):
    bs2 = malam[2021]["BS2"]
    assert bs2.status == "not_applicable" and bs2.reason.startswith("missing:")
