"""Accounting-identity checks on a canonical sheet (canonical-financials: Data-quality checks).

Each check states ``left = right(inputs)`` over canonical fields, per fiscal year, and is

- ``passed`` when ``|left − right| ≤ max(0.5% × the largest |term|, 1,000 base units)``, a tolerance that
  absorbs rounding between statements reported in thousands and in units;
- ``failed`` otherwise, with both sides and the difference;
- ``not_applicable`` when a cell it needs is missing, or when one of its cells was derived by a rule that
  embodies this very identity (the check would only confirm itself).

A ratio whose inputs take part in a failed check is reported with low confidence (``fin/ratios.py``).
Pure: no I/O.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from stock_analyzer.fin.canonical import Sheet

CheckStatus = Literal["passed", "failed", "not_applicable"]

RELATIVE_TOLERANCE = Decimal("0.005")
ABSOLUTE_TOLERANCE = Decimal(1000)


@dataclass(frozen=True)
class Check:
    id: str
    label_he: str
    templates: frozenset[str]
    left: str
    inputs: tuple[str, ...]
    right: Callable[..., Decimal]

    @property
    def cells(self) -> tuple[str, ...]:
        return (self.left, *self.inputs)


class CheckResult(BaseModel):
    id: str
    label_he: str
    fiscal_year: int
    status: CheckStatus
    cells: list[str]
    left: Decimal | None = None
    right: Decimal | None = None
    difference: Decimal | None = None
    reason: str | None = None  # why not_applicable


ALL = frozenset({"industrial", "bank", "insurer"})
INDUSTRIAL = frozenset({"industrial"})

CHECKS: tuple[Check, ...] = (
    Check(
        "BS1",
        "סך הנכסים שווה להתחייבויות ולהון",
        ALL,
        "total_assets",
        ("total_liabilities", "total_equity"),
        lambda liabilities, equity: liabilities + equity,
    ),
    Check(
        "BS2",
        "סך החוב שווה לחוב לזמן קצר ולזמן ארוך",
        INDUSTRIAL,
        "total_debt",
        ("current_debt", "noncurrent_debt"),
        lambda current, noncurrent: current + noncurrent,
    ),
    Check(
        "BS3",
        "חוב נטו שווה לחוב פחות מזומנים והשקעות לזמן קצר",
        INDUSTRIAL,
        "net_debt",
        ("total_debt", "cash_and_st_investments"),
        lambda debt, cash: debt - cash,
    ),
    Check(
        "BS5",
        "סך ההון שווה להון המיוחס לבעלי המניות ולזכויות שאינן מקנות שליטה",
        ALL,
        "total_equity",
        ("common_equity", "minority_interest"),
        lambda common, minority: common + minority,
    ),
    Check(
        "IS1",
        "רווח גולמי שווה להכנסות פחות עלות ההכנסות",
        INDUSTRIAL,
        "gross_profit",
        ("revenue", "cost_of_revenue"),
        lambda revenue, cost: revenue - cost,
    ),
    Check(
        "IS2",
        "רווח לבעלי המניות שווה לרווח המאוחד פחות חלק זכויות המיעוט",
        ALL,
        "net_income_parent",
        ("net_income_consolidated", "minority_interest_in_earnings"),
        lambda consolidated, minority: consolidated - minority,
    ),
    Check(
        "CF1",
        "תזרימי הפעילות השוטפת, ההשקעה והמימון מסתכמים לשינוי במזומנים",
        INDUSTRIAL,
        "net_change_in_cash",
        ("cfo", "cfi", "cff"),
        lambda cfo, cfi, cff: cfo + cfi + cff,
    ),
    Check(
        "CF3",
        "הרווח הנקי בדוח התזרים שווה לרווח הנקי המאוחד",
        INDUSTRIAL,
        "net_income_cf",
        ("net_income_consolidated",),
        lambda consolidated: consolidated,
    ),
)


def tolerance(*terms: Decimal) -> Decimal:
    return max(RELATIVE_TOLERANCE * max(abs(t) for t in terms), ABSOLUTE_TOLERANCE)


def run_check(check: Check, sheet: Sheet, fiscal_year: int) -> CheckResult:
    base = {
        "id": check.id,
        "label_he": check.label_he,
        "fiscal_year": fiscal_year,
        "cells": list(check.cells),
    }
    cells = [sheet.cell(fiscal_year, name) for name in check.cells]
    missing = [name for name, c in zip(check.cells, cells, strict=True) if c is None or c.value is None]
    if missing:
        return CheckResult(**base, status="not_applicable", reason=f"missing: {', '.join(missing)}")
    circular = [c.field for c in cells if c is not None and c.embodies == check.id]
    if circular:
        return CheckResult(
            **base, status="not_applicable", reason=f"derived by this identity: {', '.join(circular)}"
        )
    left, *inputs = (c.value for c in cells if c is not None and c.value is not None)
    right = check.right(*inputs)
    difference = left - right
    ok = abs(difference) <= tolerance(left, *inputs)
    return CheckResult(
        **base, status="passed" if ok else "failed", left=left, right=right, difference=difference
    )


def run_checks(sheet: Sheet) -> dict[int, list[CheckResult]]:
    """Every check that applies to the sheet's template, for every fiscal year."""
    applicable = [c for c in CHECKS if sheet.template in c.templates]
    return {fy: [run_check(c, sheet, fy) for c in applicable] for fy in sheet.years}


def failed_by_cell(results: list[CheckResult]) -> dict[str, list[str]]:
    """Field → ids of the failed checks it took part in (one fiscal year's results)."""
    out: dict[str, list[str]] = {}
    for r in results:
        if r.status == "failed":
            for name in r.cells:
                out.setdefault(name, []).append(r.id)
    return out
