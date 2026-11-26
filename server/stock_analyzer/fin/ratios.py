"""Core ratios, year-over-year changes and confidence (financial-analysis spec, design D7).

A declarative registry: each ratio names its inputs, unit and how its change is measured. All
arithmetic is ``Decimal``. A ratio that cannot be computed has no value and a reason, never a
guess. Confidence comes from the data-quality checks: a ratio or change is ``low`` when any of
its input codes took part in a failed check for that fiscal year.

Percentages are held as fractions (gross margin ``0.1047`` is 10.47%); percentage-point changes
are differences of fractions (``-0.0013`` is −0.13 points). Display formatting is not done here.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Literal

from pydantic import BaseModel

from stock_analyzer.fin.checks import CheckResult, failed_checks_for
from stock_analyzer.fin.normalize import FinValue, decimal_str

Unit = Literal["money", "percent", "multiple", "count", "per_share"]
ChangeUnit = Literal["percent", "pp", "multiple"]
Confidence = Literal["high", "low"]

PRECISION = 28  # significant digits for division; inputs are exact


class NoValue(Exception):
    """A ratio has no meaningful value for this year; the message is the reason."""


@dataclass(frozen=True)
class RatioDef:
    code: str
    name_he: str
    group: str
    unit: Unit
    inputs: tuple[str, ...]
    formula: Callable[[Mapping[str, Decimal]], Decimal]
    definition_he: str

    @property
    def change_unit(self) -> ChangeUnit:
        return {"percent": "pp", "multiple": "multiple"}.get(self.unit, "percent")  # type: ignore[return-value]


def _div(numerator: Decimal, denominator: Decimal, what: str, *, positive: bool = False) -> Decimal:
    if denominator == 0:
        raise NoValue(f"{what} is zero")
    if positive and denominator < 0:
        raise NoValue(f"{what} is negative, so the ratio is not meaningful")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return numerator / denominator


RATIOS: tuple[RatioDef, ...] = (
    RatioDef(
        "gross_margin",
        "שיעור רווח גולמי",
        "profitability",
        "percent",
        ("gross_profit", "revenue"),
        lambda v: _div(v["gross_profit"], v["revenue"], "revenue", positive=True),
        "רווח גולמי חלקי הכנסות",
    ),
    RatioDef(
        "operating_margin",
        "שיעור רווח תפעולי",
        "profitability",
        "percent",
        ("operating_income_loss", "revenue"),
        lambda v: _div(v["operating_income_loss"], v["revenue"], "revenue", positive=True),
        "רווח תפעולי חלקי הכנסות",
    ),
    RatioDef(
        "ebitda_margin",
        "שיעור EBITDA",
        "profitability",
        "percent",
        ("ebitda", "revenue"),
        lambda v: _div(v["ebitda"], v["revenue"], "revenue", positive=True),
        "EBITDA חלקי הכנסות",
    ),
    RatioDef(
        "net_margin",
        "שיעור רווח נקי",
        "profitability",
        "percent",
        ("net_income_loss", "revenue"),
        lambda v: _div(v["net_income_loss"], v["revenue"], "revenue", positive=True),
        "רווח נקי המיוחס לבעלי המניות חלקי הכנסות",
    ),
    RatioDef(
        "free_cash_flow",
        "תזרים מזומנים חופשי",
        "cash_flow",
        "money",
        ("cash_from_operations", "capital_expenditure_cf"),
        lambda v: v["cash_from_operations"] + v["capital_expenditure_cf"],  # capex is negative
        "תזרים מפעילות שוטפת פחות השקעות ברכוש קבוע",
    ),
    RatioDef(
        "free_cash_flow_margin",
        "שיעור תזרים חופשי",
        "cash_flow",
        "percent",
        ("cash_from_operations", "capital_expenditure_cf", "revenue"),
        lambda v: _div(
            v["cash_from_operations"] + v["capital_expenditure_cf"], v["revenue"], "revenue", positive=True
        ),
        "תזרים מזומנים חופשי חלקי הכנסות",
    ),
    RatioDef(
        "cfo_to_net_income",
        "תזרים שוטף לרווח נקי",
        "cash_flow",
        "multiple",
        ("cash_from_operations", "consolidated_net_income"),
        lambda v: _div(
            v["cash_from_operations"], v["consolidated_net_income"], "consolidated net income", positive=True
        ),
        "תזרים מפעילות שוטפת חלקי רווח נקי מאוחד",
    ),
    RatioDef(
        "debt_to_equity",
        "חוב להון",
        "leverage",
        "multiple",
        ("total_debt_bs", "total_equity"),
        lambda v: _div(v["total_debt_bs"], v["total_equity"], "total equity", positive=True),
        "סך חוב חלקי סך הון",
    ),
    RatioDef(
        "net_debt_to_ebitda",
        "חוב נטו ל-EBITDA",
        "leverage",
        "multiple",
        ("net_debt", "ebitda"),
        lambda v: _div(v["net_debt"], v["ebitda"], "EBITDA", positive=True),
        "חוב נטו חלקי EBITDA",
    ),
    RatioDef(
        "equity_to_assets",
        "הון לסך מאזן",
        "leverage",
        "percent",
        ("total_equity", "total_assets"),
        lambda v: _div(v["total_equity"], v["total_assets"], "total assets", positive=True),
        "סך הון חלקי סך נכסים",
    ),
    RatioDef(
        "short_term_debt_share",
        "שיעור החוב לזמן קצר",
        "leverage",
        "percent",
        ("total_current_debt_bs", "total_debt_bs"),
        lambda v: _div(v["total_current_debt_bs"], v["total_debt_bs"], "total debt", positive=True),
        "חוב לזמן קצר חלקי סך חוב",
    ),
    RatioDef(
        "current_ratio",
        "יחס שוטף",
        "liquidity",
        "multiple",
        ("total_current_assets", "total_current_liabilities"),
        lambda v: _div(
            v["total_current_assets"], v["total_current_liabilities"], "current liabilities", positive=True
        ),
        "נכסים שוטפים חלקי התחייבויות שוטפות",
    ),
    RatioDef(
        "cash_ratio",
        "יחס מזומנים",
        "liquidity",
        "multiple",
        ("total_cash_and_short_term_investments", "total_current_liabilities"),
        lambda v: _div(
            v["total_cash_and_short_term_investments"],
            v["total_current_liabilities"],
            "current liabilities",
            positive=True,
        ),
        "מזומנים והשקעות לזמן קצר חלקי התחייבויות שוטפות",
    ),
)

RATIO_BY_CODE: dict[str, RatioDef] = {r.code: r for r in RATIOS}


class RatioValue(BaseModel):
    code: str
    name_he: str
    group: str
    unit: Unit
    fiscal_year: int
    value: str | None  # exact decimal string
    inputs: dict[str, str | None]  # code -> exact value (None when missing)
    reason: str | None  # why there is no value
    confidence: Confidence
    failed_checks: list[str]


class Change(BaseModel):
    kind: Literal["FIN", "RATIO"]
    code: str
    name_he: str
    unit: ChangeUnit
    from_year: int
    to_year: int
    old: str | None
    new: str | None
    value: str | None  # exact decimal string: a fraction for percent/pp, a plain difference for multiples
    reason: str | None
    confidence: Confidence
    failed_checks: list[str]


def fin_unit(v: FinValue) -> Unit:
    if v.code.endswith("_eps"):
        return "per_share"
    if v.statement == "supplemental" and ("shares" in v.code or "employees" in v.code):
        return "count"
    return "money"


def _by_year(values: Iterable[FinValue]) -> dict[int, dict[str, Decimal]]:
    out: dict[int, dict[str, Decimal]] = {}
    for v in values:
        out.setdefault(v.fiscal_year, {})[v.code] = v.value
    return out


def compute_ratios(values: Iterable[FinValue], checks: list[CheckResult]) -> list[RatioValue]:
    """Every core ratio for every fiscal year present, ordered by year then registry order."""
    by_year = _by_year(values)
    out: list[RatioValue] = []
    for year in sorted(by_year):
        present = by_year[year]
        for r in RATIOS:
            missing = [c for c in r.inputs if c not in present]
            value: Decimal | None = None
            reason: str | None = None
            if missing:
                reason = "missing input: " + ", ".join(missing)
            else:
                try:
                    value = r.formula(present)
                except NoValue as exc:
                    reason = str(exc)
            failed = failed_checks_for(r.inputs, year, checks)
            out.append(
                RatioValue(
                    code=r.code,
                    name_he=r.name_he,
                    group=r.group,
                    unit=r.unit,
                    fiscal_year=year,
                    value=decimal_str(value) if value is not None else None,
                    inputs={c: (decimal_str(present[c]) if c in present else None) for c in r.inputs},
                    reason=reason,
                    confidence="low" if failed else "high",
                    failed_checks=failed,
                )
            )
    return out


def change_value(
    old: Decimal | None, new: Decimal | None, unit: ChangeUnit
) -> tuple[Decimal | None, str | None]:
    """The change from ``old`` to ``new`` in ``unit``, or ``None`` with a reason."""
    if old is None or new is None:
        return None, "a value is missing in one of the years"
    if unit in ("pp", "multiple"):
        return new - old, None
    if old == 0:
        return None, "the previous value is zero"
    if (old < 0) != (new < 0) and new != 0:
        return None, "the sign changed between the years"
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return (new - old) / abs(old), None


def compute_changes(
    values: Iterable[FinValue], ratios: Iterable[RatioValue], checks: list[CheckResult]
) -> list[Change]:
    """Changes between consecutive fiscal years for every normalized value and core ratio."""
    values = list(values)
    years = sorted({v.fiscal_year for v in values})
    pairs = list(zip(years, years[1:], strict=False))
    out: list[Change] = []

    fin: dict[str, dict[int, FinValue]] = {}
    for v in values:
        fin.setdefault(v.code, {})[v.fiscal_year] = v
    for code in sorted(fin):
        for y0, y1 in pairs:
            a, b = fin[code].get(y0), fin[code].get(y1)
            if a is None and b is None:
                continue
            value, reason = change_value(a.value if a else None, b.value if b else None, "percent")
            failed = sorted(
                set(failed_checks_for([code], y0, checks)) | set(failed_checks_for([code], y1, checks))
            )
            label = (b or a).label  # type: ignore[union-attr]
            out.append(
                Change(
                    kind="FIN",
                    code=code,
                    name_he=label,
                    unit="percent",
                    from_year=y0,
                    to_year=y1,
                    old=decimal_str(a.value) if a else None,
                    new=decimal_str(b.value) if b else None,
                    value=decimal_str(value) if value is not None else None,
                    reason=reason,
                    confidence="low" if failed else "high",
                    failed_checks=failed,
                )
            )

    by_code: dict[str, dict[int, RatioValue]] = {}
    for r in ratios:
        by_code.setdefault(r.code, {})[r.fiscal_year] = r
    for definition in RATIOS:
        series = by_code.get(definition.code, {})
        for y0, y1 in pairs:
            a, b = series.get(y0), series.get(y1)
            old = Decimal(a.value) if a and a.value is not None else None
            new = Decimal(b.value) if b and b.value is not None else None
            value, reason = change_value(old, new, definition.change_unit)
            failed = sorted(set(a.failed_checks if a else []) | set(b.failed_checks if b else []))
            out.append(
                Change(
                    kind="RATIO",
                    code=definition.code,
                    name_he=definition.name_he,
                    unit=definition.change_unit,
                    from_year=y0,
                    to_year=y1,
                    old=decimal_str(old) if old is not None else None,
                    new=decimal_str(new) if new is not None else None,
                    value=decimal_str(value) if value is not None else None,
                    reason=reason,
                    confidence="low" if failed else "high",
                    failed_checks=failed,
                )
            )
    return out
