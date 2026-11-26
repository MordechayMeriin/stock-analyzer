"""Ratios over a canonical sheet, as year-over-year series (financial-ratios spec).

- A declarative :data:`RATIOS` registry: code, Hebrew name, group, unit, direction, change threshold, the
  templates it applies to, and a formula over canonical fields.
- Exact ``Decimal`` arithmetic; percentages are fractions (0.1047 = 10.47%).
- Balance-sheet denominators listed in ``avg_inputs`` use (opening + closing) / 2 when the year before
  has the value, else the closing value (``avg_used`` says which).
- An uncomputable value is missing with a reason code, never estimated.
- Confidence is ``low`` when an input (including an opening balance or a prior-year value) took part in a
  failed data-quality check or was derived; the failed check ids and derived inputs are listed.
- Each year's delta from the year before gets a status from the ratio's direction and threshold.

Pure: no I/O.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from stock_analyzer.fin.canonical import Cell, Sheet, field_def
from stock_analyzer.fin.checks import CheckResult, failed_by_cell

Unit = Literal["percent", "ratio", "amount", "days"]
Direction = Literal["higher", "lower", "neutral"]
Status = Literal["improved", "deteriorated", "changed", "stable", "na"]
Confidence = Literal["high", "low"]

ANNUAL_FILING_TYPES = {"10-K", "10-K-ESEF"}

GROUP_LABELS_HE: dict[str, str] = {
    "profitability": "רווחיות",
    "growth": "צמיחה",
    "returns": "תשואה",
    "liquidity": "נזילות",
    "leverage": "מינוף ואיתנות",
    "cash_flow": "תזרים מזומנים",
    "credit": "אשראי ופיקדונות",
    "capital": "הלימות הון",
}


class Uncomputable(Exception):  # noqa: N818 - a reason code, not a failure
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def div(numerator: Decimal, denominator: Decimal, *, positive: bool = False) -> Decimal:
    """``positive``: a negative denominator makes the ratio meaningless (equity, prior-year profit)."""
    if denominator == 0:
        raise Uncomputable("zero_denominator")
    if positive and denominator < 0:
        raise Uncomputable("negative_denominator")
    return numerator / denominator


def growth(current: Decimal, prior: Decimal) -> Decimal:
    return div(current, prior, positive=True) - 1


@dataclass(frozen=True)
class Ratio:
    code: str
    name_he: str
    group: str
    unit: Unit
    direction: Direction
    threshold: Decimal  # |delta| below this is "stable"; relative change for amounts
    templates: frozenset[str]
    inputs: tuple[str, ...]  # current-year fields
    fn: Callable[[dict[str, Decimal]], Decimal]  # keys: field, and "prior:<field>" for prior_inputs
    avg_inputs: tuple[str, ...] = ()  # subset of inputs averaged with the opening balance
    prior_inputs: tuple[str, ...] = ()  # fields needed from fiscal year − 1
    reported: bool = False  # passed through from a canonical cell, never recomputed


ALL = frozenset({"industrial", "bank", "insurer"})
IND = frozenset({"industrial"})
BANK = frozenset({"bank"})
D = Decimal


def _margin(code: str, name_he: str, numerator: str, threshold: str = "0.005") -> Ratio:
    return Ratio(
        code,
        name_he,
        "profitability",
        "percent",
        "higher",
        D(threshold),
        IND,
        (numerator, "revenue"),
        lambda v, n=numerator: div(v[n], v["revenue"]),
    )


def _growth(code: str, name_he: str, field: str, threshold: str, templates: frozenset[str]) -> Ratio:
    return Ratio(
        code,
        name_he,
        "growth",
        "percent",
        "higher",
        D(threshold),
        templates,
        (field,),
        lambda v, f=field: growth(v[f], v[f"prior:{f}"]),
        prior_inputs=(field,),
    )


def _reported(code: str, name_he: str) -> Ratio:
    return Ratio(
        code,
        name_he,
        "capital",
        "percent",
        "higher",
        D("0.005"),
        BANK,
        (code,),
        lambda v, c=code: v[c],
        reported=True,
    )


# Thresholds follow plan.md §3.3 where it gives one; the rest were set by unit. Checked on Malam FY2021–FY2025
# (task 4.3): they give a mix of stable, improved and deteriorated years rather than flagging every move
# or none, e.g. gross margin 10.60% → 10.47% is stable while 11.24% → 10.60% is deteriorated. Bank
# thresholds are per ratio, scaled to typical levels (a ~0.2% non-performing-loan ratio moves by 0.1pp).
RATIOS: tuple[Ratio, ...] = (
    # profitability (industrial)
    _margin("gross_margin", "שיעור רווח גולמי", "gross_profit"),
    _margin("operating_margin", "שיעור רווח תפעולי", "operating_income"),
    _margin("ebitda_margin", "שיעור EBITDA", "ebitda"),
    _margin("net_margin", "שיעור רווח נקי", "net_income_parent"),
    # growth
    _growth("revenue_growth", "צמיחה בהכנסות", "revenue", "0.03", IND),
    _growth("net_income_growth", "צמיחה ברווח הנקי", "net_income_parent", "0.10", ALL),
    _growth("eps_growth", "צמיחה ברווח למניה", "basic_eps", "0.10", ALL),
    # returns (every template): parent's net income for ROE, consolidated for ROA (plan.md §3.1)
    Ratio(
        "roe",
        "תשואה על ההון",
        "returns",
        "percent",
        "higher",
        D("0.015"),
        ALL,
        ("net_income_parent", "common_equity"),
        lambda v: div(v["net_income_parent"], v["common_equity"], positive=True),
        avg_inputs=("common_equity",),
    ),
    Ratio(
        "roa",
        "תשואה על הנכסים",
        "returns",
        "percent",
        "higher",
        D("0.005"),
        ALL,
        ("net_income_consolidated", "total_assets"),
        lambda v: div(v["net_income_consolidated"], v["total_assets"], positive=True),
        avg_inputs=("total_assets",),
    ),
    # liquidity (industrial)
    Ratio(
        "current_ratio",
        "יחס שוטף",
        "liquidity",
        "ratio",
        "higher",
        D("0.1"),
        IND,
        ("current_assets", "current_liabilities"),
        lambda v: div(v["current_assets"], v["current_liabilities"], positive=True),
    ),
    Ratio(
        "quick_ratio",
        "יחס מהיר",
        "liquidity",
        "ratio",
        "higher",
        D("0.1"),
        IND,
        ("cash", "receivables", "current_liabilities"),
        lambda v: div(v["cash"] + v["receivables"], v["current_liabilities"], positive=True),
    ),
    # leverage
    Ratio(
        "equity_to_assets",
        "הון עצמי לסך נכסים",
        "leverage",
        "percent",
        "higher",
        D("0.02"),
        ALL,
        ("total_equity", "total_assets"),
        lambda v: div(v["total_equity"], v["total_assets"], positive=True),
    ),
    Ratio(
        "debt_to_equity",
        "חוב להון",
        "leverage",
        "ratio",
        "lower",
        D("0.1"),
        IND,
        ("total_debt", "total_equity"),
        lambda v: div(v["total_debt"], v["total_equity"], positive=True),
    ),
    # cash flow
    Ratio(
        "cfo_to_net_income",
        "תזרים מפעילות שוטפת לרווח נקי",
        "cash_flow",
        "ratio",
        "higher",
        D("0.2"),
        ALL,
        ("cfo", "net_income_consolidated"),
        lambda v: div(v["cfo"], v["net_income_consolidated"], positive=True),
    ),
    Ratio(
        "free_cash_flow",
        "תזרים מזומנים חופשי",
        "cash_flow",
        "amount",
        "higher",
        D("0.10"),
        IND,
        ("cfo", "capex"),
        lambda v: v["cfo"] + v["capex"],  # capex is reported negative
    ),
    Ratio(
        "fcf_margin",
        "שיעור תזרים חופשי מההכנסות",
        "cash_flow",
        "percent",
        "higher",
        D("0.005"),
        IND,
        ("cfo", "capex", "revenue"),
        lambda v: div(v["cfo"] + v["capex"], v["revenue"]),
    ),
    # credit (banks)
    Ratio(
        "loans_to_deposits",
        "אשראי לפיקדונות",
        "credit",
        "percent",
        "neutral",
        D("0.02"),
        BANK,
        ("loans_net", "customer_deposits"),
        lambda v: div(v["loans_net"], v["customer_deposits"], positive=True),
    ),
    Ratio(
        "npl_ratio",
        "שיעור חובות פגומים",
        "credit",
        "percent",
        "lower",
        D("0.001"),
        BANK,
        ("nonperforming_loans", "gross_loans"),
        lambda v: div(v["nonperforming_loans"], v["gross_loans"], positive=True),
    ),
    Ratio(
        "loan_loss_coverage",
        "כיסוי חובות פגומים בהפרשה",
        "credit",
        "ratio",
        "higher",
        D("0.5"),
        BANK,
        ("loan_loss_allowance", "nonperforming_loans"),
        lambda v: div(v["loan_loss_allowance"], v["nonperforming_loans"], positive=True),
    ),
    # capital (banks): as reported by the provider
    _reported("cet1_ratio", "יחס הון עצמי רובד 1"),
    _reported("tier1_ratio", "יחס הון רובד 1"),
    _reported("total_capital_ratio", "יחס הון כולל"),
    _reported("leverage_ratio", "יחס מינוף"),
)

RATIO_BY_CODE: dict[str, Ratio] = {r.code: r for r in RATIOS}


def ratios_for(template: str) -> tuple[Ratio, ...]:
    return tuple(r for r in RATIOS if template in r.templates)


class RatioValue(BaseModel):
    code: str
    fiscal_year: int
    value: Decimal | None
    basis: Literal["computed", "reported"]
    missing_reason: str | None = (
        None  # missing_input:<field> | missing_prior_input:<field> | zero_denominator | negative_denominator | no_prior_year
    )
    missing_message_he: str | None = None
    confidence: Confidence = "high"
    failed_checks: list[
        str
    ] = []  # check ids; "<id>:<fy>" when it failed in another year (opening/prior values)
    derived_inputs: list[str] = []  # "<field>:<fy>"
    avg_used: bool = False
    inputs: dict[str, Decimal] = {}  # field (closing) | "opening:<field>" | "prior:<field>" → value
    delta: Decimal | None = None
    status: Status = "na"
    notes: list[str] = []


class RatioSeries(BaseModel):
    code: str
    name_he: str
    group: str
    unit: Unit
    direction: Direction
    threshold: Decimal
    values: dict[int, RatioValue]  # fiscal year → value


def _missing_message(reason: str, template: str) -> str:
    kind, _, fields = reason.partition(":")
    label = ", ".join(field_def(template, f).label_he for f in fields.split(",")) if fields else ""
    return {
        "missing_input": f"חסר נתון: {label}",
        "missing_prior_input": f"חסר נתון לשנה הקודמת: {label}",
        "zero_denominator": "המכנה אפס",
        "negative_denominator": "המכנה שלילי, ולכן היחס אינו משמעותי",
        "no_prior_year": "אין נתוני שנה קודמת",
    }[kind]


def _compute_one(ratio: Ratio, sheet: Sheet, fy: int, failed: dict[int, dict[str, list[str]]]) -> RatioValue:
    used: list[Cell] = []
    values: dict[str, Decimal] = {}  # what the formula sees (averages already applied)
    shown: dict[str, Decimal] = {}  # what the output reports: closing, opening and prior values
    avg_used = False
    reason: str | None = None

    missing = [n for n in ratio.inputs if sheet.value(fy, n) is None]
    if missing:
        reason = f"missing_input:{','.join(missing)}"
    for name in ratio.inputs:
        cell = sheet.cell(fy, name)
        if cell is None or cell.value is None:
            continue
        used.append(cell)
        values[name] = shown[name] = cell.value
        if name in ratio.avg_inputs:
            opening = sheet.cell(fy - 1, name)
            if opening is not None and opening.value is not None:
                used.append(opening)
                shown[f"opening:{name}"] = opening.value
                values[name] = (opening.value + cell.value) / 2
                avg_used = True
    for name in ratio.prior_inputs:
        if fy - 1 not in sheet.cells:
            reason = reason or "no_prior_year"
            continue
        prior = sheet.cell(fy - 1, name)
        if prior is None or prior.value is None:
            reason = reason or f"missing_prior_input:{name}"
            continue
        used.append(prior)
        values[f"prior:{name}"] = shown[f"prior:{name}"] = prior.value

    value: Decimal | None = None
    if reason is None:
        try:
            value = ratio.fn(values)
        except Uncomputable as exc:
            reason = exc.reason

    failed_checks: list[str] = []
    derived: list[str] = []
    notes: set[str] = set()
    for cell in used if value is not None else []:  # confidence and notes describe a value
        for check_id in failed.get(cell.fiscal_year, {}).get(cell.field, []):
            label = check_id if cell.fiscal_year == fy else f"{check_id}:{cell.fiscal_year}"
            if label not in failed_checks:
                failed_checks.append(label)
        if cell.basis == "derived":
            derived.append(f"{cell.field}:{cell.fiscal_year}")
        if cell.source_filing_type and cell.source_filing_type not in ANNUAL_FILING_TYPES:
            notes.add("non_annual_source")
    return RatioValue(
        code=ratio.code,
        fiscal_year=fy,
        value=value,
        basis="reported" if ratio.reported else "computed",
        missing_reason=reason,
        missing_message_he=_missing_message(reason, sheet.template) if reason else None,
        confidence="low" if failed_checks or derived else "high",
        failed_checks=failed_checks,
        derived_inputs=derived,
        avg_used=avg_used,
        inputs=shown,
        notes=sorted(notes),
    )


def change(ratio: Ratio, current: Decimal | None, previous: Decimal | None) -> tuple[Decimal | None, Status]:
    """Delta from the year before (relative for amounts) and its status."""
    if current is None or previous is None:
        return None, "na"
    if ratio.unit == "amount":
        if previous == 0:
            return None, "na"
        delta = (current - previous) / abs(previous)
    else:
        delta = current - previous
    if abs(delta) < ratio.threshold:
        return delta, "stable"
    if ratio.direction == "neutral":
        return delta, "changed"
    better = delta > 0 if ratio.direction == "higher" else delta < 0
    return delta, "improved" if better else "deteriorated"


def compute(sheet: Sheet, checks: dict[int, list[CheckResult]]) -> list[RatioSeries]:
    """Every ratio of the sheet's template, for every fiscal year in the sheet, in registry order."""
    failed = {fy: failed_by_cell(results) for fy, results in checks.items()}
    series: list[RatioSeries] = []
    for ratio in ratios_for(sheet.template):
        values = {fy: _compute_one(ratio, sheet, fy, failed) for fy in sheet.years}
        for fy, rv in values.items():
            prev = values.get(fy - 1)
            rv.delta, rv.status = change(ratio, rv.value, prev.value if prev else None)
        series.append(
            RatioSeries(
                code=ratio.code,
                name_he=ratio.name_he,
                group=ratio.group,
                unit=ratio.unit,
                direction=ratio.direction,
                threshold=ratio.threshold,
                values=values,
            )
        )
    return series
