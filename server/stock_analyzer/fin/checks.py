"""Data-quality checks on normalized values, before any ratio (plan.md §3.2, financial-analysis spec).

Provider data can be internally inconsistent: Malam FY2025 fails five identities. Each check
has a stable id, runs per fiscal year, and reports ``pass``, ``fail`` or ``not_run`` (a required
input is missing: an unrun check is never reported as passed). A failure names its inputs, so
ratios built on those inputs can be marked low-confidence (see :func:`failed_checks_for`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from stock_analyzer.fin.normalize import FinValue, decimal_str

CheckStatus = Literal["pass", "fail", "not_run"]

# investing items other than capital expenditure (check CF2)
OTHER_INVESTING = (
    "cash_acquisitions_cf",
    "divestitures_cf",
    "sale_of_property_plant_equipment_cf",
    "sale_purchase_of_intangible_assets_cf",
)


@dataclass(frozen=True)
class Outcome:
    passed: bool
    expected: Decimal | None
    actual: Decimal | None


@dataclass(frozen=True)
class CheckDef:
    check_id: str
    description_he: str
    required: tuple[str, ...]
    optional: tuple[str, ...]
    evaluate: Callable[[Mapping[str, Decimal], Decimal], Outcome]

    @property
    def inputs(self) -> tuple[str, ...]:
        return self.required + self.optional


class CheckResult(BaseModel):
    check_id: str
    fiscal_year: int
    status: CheckStatus
    description_he: str
    inputs: dict[str, str]  # code -> exact value, for the inputs that were present
    missing: list[str]  # required inputs that were missing (status not_run)
    expected: str | None
    actual: str | None
    tolerance: str | None


def _close(a: Decimal, b: Decimal, tol: Decimal, base: Decimal) -> bool:
    return abs(a - b) <= tol * abs(base)


def _bs1(v: Mapping[str, Decimal], tol: Decimal) -> Outcome:
    expected = v["total_liabilities"] + v["total_equity"]
    return Outcome(_close(v["total_assets"], expected, tol, v["total_assets"]), expected, v["total_assets"])


def _bs2(v: Mapping[str, Decimal], tol: Decimal) -> Outcome:
    expected = v["total_current_debt_bs"] + v["total_non_current_debt_bs"]
    return Outcome(
        _close(v["total_debt_bs"], expected, tol, v["total_debt_bs"]), expected, v["total_debt_bs"]
    )


def _bs3(v: Mapping[str, Decimal], tol: Decimal) -> Outcome:
    expected = v["total_debt_bs"] - v["total_cash_and_short_term_investments"]
    return Outcome(_close(v["net_debt"], expected, tol, v["total_debt_bs"]), expected, v["net_debt"])


def _bs4(v: Mapping[str, Decimal], tol: Decimal) -> Outcome:
    # identified current assets must not exceed the total, nor leave more than `tol` of it unexplained
    identified = v["cash_and_equivalents"] + v["total_receivables"] + v.get("inventory", Decimal(0))
    total = v["total_current_assets"]
    if total <= 0:
        return Outcome(False, identified, total)
    gap_share = (total - identified) / total
    return Outcome(Decimal(0) <= gap_share <= tol, identified, total)


def _bs5(v: Mapping[str, Decimal], tol: Decimal) -> Outcome:
    expected = v["total_common_equity"] + v["minority_interest"]
    return Outcome(_close(v["total_equity"], expected, tol, v["total_equity"]), expected, v["total_equity"])


def _is1(v: Mapping[str, Decimal], tol: Decimal) -> Outcome:
    expected = v["revenue"] - v["cost_of_revenue"]
    return Outcome(_close(v["gross_profit"], expected, tol, v["revenue"]), expected, v["gross_profit"])


def _is2(v: Mapping[str, Decimal], tol: Decimal) -> Outcome:
    expected = v["consolidated_net_income"] - v["minority_interest_in_earnings"]
    return Outcome(
        _close(v["net_income_loss"], expected, tol, v["consolidated_net_income"]),
        expected,
        v["net_income_loss"],
    )


def _is3(v: Mapping[str, Decimal], tol: Decimal) -> Outcome:
    # operating income minus net interest should come close to pre-tax earnings; the tolerance
    # leaves room for unusual items, which the provider does not break out
    ebt = v["earnings_before_tax_including_unusual_items"]
    expected = v["operating_income_loss"] - v["net_interest_expense"]
    return Outcome(_close(ebt, expected, tol, ebt), expected, ebt)


def _cf1(v: Mapping[str, Decimal], tol: Decimal) -> Outcome:
    flows = (v["cash_from_operations"], v["cash_from_investing"], v["cash_from_financing"])
    total = sum(flows, Decimal(0))
    base = sum((abs(f) for f in flows), Decimal(0))
    return Outcome(_close(total, v["net_change_in_cash_cf"], tol, base), v["net_change_in_cash_cf"], total)


def _cf2(v: Mapping[str, Decimal], tol: Decimal) -> Outcome:
    others = [v[c] for c in OTHER_INVESTING if c in v and v[c] != 0]
    same = v["cash_from_investing"] == v["capital_expenditure_cf"]
    return Outcome(not (same and others), None, v["cash_from_investing"])


CHECKS: tuple[CheckDef, ...] = (
    CheckDef(
        "BS1",
        "סך הנכסים שווה לסך ההתחייבויות וההון",
        ("total_assets", "total_liabilities", "total_equity"),
        (),
        _bs1,
    ),
    CheckDef(
        "BS2",
        "סך החוב שווה לחוב לזמן קצר ועוד חוב לזמן ארוך",
        ("total_debt_bs", "total_current_debt_bs", "total_non_current_debt_bs"),
        (),
        _bs2,
    ),
    CheckDef(
        "BS3",
        "החוב נטו שווה לחוב פחות מזומנים והשקעות לזמן קצר",
        ("net_debt", "total_debt_bs", "total_cash_and_short_term_investments"),
        (),
        _bs3,
    ),
    CheckDef(
        "BS4",
        "מזומנים, לקוחות ומלאי מסבירים את רוב הנכסים השוטפים",
        ("total_current_assets", "cash_and_equivalents", "total_receivables"),
        ("inventory",),
        _bs4,
    ),
    CheckDef(
        "BS5",
        "סך ההון קרוב להון המיוחס לבעלי המניות ועוד זכויות שאינן מקנות שליטה",
        ("total_equity", "total_common_equity", "minority_interest"),
        (),
        _bs5,
    ),
    CheckDef(
        "IS1",
        "הרווח הגולמי שווה להכנסות פחות עלות ההכנסות",
        ("gross_profit", "revenue", "cost_of_revenue"),
        (),
        _is1,
    ),
    CheckDef(
        "IS2",
        "הרווח לבעלי המניות שווה לרווח המאוחד פחות חלק הזכויות שאינן מקנות שליטה",
        ("net_income_loss", "consolidated_net_income", "minority_interest_in_earnings"),
        (),
        _is2,
    ),
    CheckDef(
        "IS3",
        "הרווח התפעולי פחות הוצאות המימון נטו קרוב לרווח לפני מס",
        ("operating_income_loss", "net_interest_expense", "earnings_before_tax_including_unusual_items"),
        (),
        _is3,
    ),
    CheckDef(
        "CF1",
        "סכום התזרימים משלוש הפעילויות שווה לשינוי במזומנים",
        ("cash_from_operations", "cash_from_investing", "cash_from_financing", "net_change_in_cash_cf"),
        (),
        _cf1,
    ),
    CheckDef(
        "CF2",
        "תזרים ההשקעה אינו שווה להשקעות ברכוש קבוע בלבד כשיש פריטי השקעה אחרים",
        ("cash_from_investing", "capital_expenditure_cf"),
        OTHER_INVESTING,
        _cf2,
    ),
)

CHECK_IDS: tuple[str, ...] = tuple(c.check_id for c in CHECKS)


def run_checks(values: Iterable[FinValue], tolerances: Mapping[str, float]) -> list[CheckResult]:
    """Every check for every fiscal year present, in a stable order (year, then check id order)."""
    by_year: dict[int, dict[str, Decimal]] = {}
    for v in values:
        by_year.setdefault(v.fiscal_year, {})[v.code] = v.value
    results: list[CheckResult] = []
    for year in sorted(by_year):
        present = by_year[year]
        for check in CHECKS:
            inputs = {c: present[c] for c in check.inputs if c in present}
            missing = [c for c in check.required if c not in present]
            tol = tolerances.get(check.check_id)
            tol_dec = Decimal(str(tol)) if tol is not None else Decimal(0)
            if missing:
                status: CheckStatus = "not_run"
                outcome = None
            else:
                outcome = check.evaluate(inputs, tol_dec)
                status = "pass" if outcome.passed else "fail"
            results.append(
                CheckResult(
                    check_id=check.check_id,
                    fiscal_year=year,
                    status=status,
                    description_he=check.description_he,
                    inputs={c: decimal_str(x) for c, x in inputs.items()},
                    missing=missing,
                    expected=decimal_str(outcome.expected)
                    if outcome and outcome.expected is not None
                    else None,
                    actual=decimal_str(outcome.actual) if outcome and outcome.actual is not None else None,
                    tolerance=str(tol) if tol is not None else None,
                )
            )
    return results


def failed_checks_for(codes: Iterable[str], fiscal_year: int, results: Iterable[CheckResult]) -> list[str]:
    """Ids of the checks that failed for ``fiscal_year`` and used any of ``codes`` as an input."""
    wanted = set(codes)
    return [
        r.check_id
        for r in results
        if r.fiscal_year == fiscal_year and r.status == "fail" and wanted & set(r.inputs)
    ]
