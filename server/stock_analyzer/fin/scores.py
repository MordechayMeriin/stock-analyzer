"""Scoring anchors and the 1-10 score arithmetic behind the company report radar.

Method (absolute scale, no sector comparison):

- An axis is a list of components. A component is one ratio code with two anchors: ``bad`` scores 1 and
  ``good`` scores 10. The component score is the ratio value mapped linearly between the anchors and
  clamped to [1, 10]. Anchors may be inverted (``bad`` > ``good``) for "lower is better" ratios.
- The axis score for a year is the mean of the component scores that have a value that year, rounded half
  up to an integer 1-10. With no component value the axis score is ``None``, never 0.
- Low-confidence ratio values are used as they are; the report only warns about them.

Anchors are fixed judgment calls (see :data:`INDUSTRIAL_AXES`, :data:`BANK_AXES`, :data:`INSURER_AXES`),
not fitted to the tracked companies. Pure: no I/O.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

D = Decimal
LOW, HIGH = D(1), D(10)


@dataclass(frozen=True)
class Component:
    code: str  # ratio code in fin/ratios.py
    bad: Decimal  # ratio value that scores 1
    good: Decimal  # ratio value that scores 10


@dataclass(frozen=True)
class AxisSpec:
    id: str
    label_he: str
    components: tuple[Component, ...]


def comp(code: str, bad: str, good: str) -> Component:
    return Component(code, D(bad), D(good))


INDUSTRIAL_AXES: tuple[AxisSpec, ...] = (
    AxisSpec(
        "stability", "יציבות", (comp("operating_margin", "0.00", "0.15"), comp("current_ratio", "0.8", "2.0"))
    ),
    AxisSpec(
        "safety", "ביטחון", (comp("equity_to_assets", "0.10", "0.60"), comp("debt_to_equity", "2.0", "0.0"))
    ),
    AxisSpec(
        "growth",
        "צמיחה",
        (comp("revenue_growth", "-0.10", "0.20"), comp("net_income_growth", "-0.30", "0.30")),
    ),
    AxisSpec("profitability", "רווחיות", (comp("roe", "0.00", "0.20"), comp("net_margin", "0.00", "0.12"))),
    AxisSpec(
        "cash_quality",
        "איכות תזרים",
        (comp("cfo_to_net_income", "0.3", "1.5"), comp("fcf_margin", "-0.05", "0.10")),
    ),
)

BANK_AXES: tuple[AxisSpec, ...] = (
    AxisSpec("profitability", "רווחיות", (comp("roe", "0.00", "0.15"),)),
    AxisSpec(
        "safety", "ביטחון", (comp("cet1_ratio", "0.08", "0.14"), comp("leverage_ratio", "0.04", "0.08"))
    ),
    AxisSpec(
        "credit",
        "איכות אשראי",
        (comp("npl_ratio", "0.05", "0.005"), comp("loan_loss_coverage", "0.5", "1.5")),
    ),
    AxisSpec("liquidity", "נזילות", (comp("loans_to_deposits", "1.1", "0.7"),)),
    AxisSpec("growth", "צמיחה", (comp("net_income_growth", "-0.30", "0.30"),)),
)

# The brief gave no insurer anchors: equity/assets of 4% to 12% spans typical insurer balance sheets.
INSURER_AXES: tuple[AxisSpec, ...] = (
    AxisSpec("profitability", "רווחיות", (comp("roe", "0.00", "0.15"),)),
    AxisSpec("safety", "ביטחון", (comp("equity_to_assets", "0.04", "0.12"),)),
    AxisSpec(
        "growth", "צמיחה", (comp("net_income_growth", "-0.30", "0.30"), comp("eps_growth", "-0.30", "0.30"))
    ),
)

AXES_BY_TEMPLATE: dict[str, tuple[AxisSpec, ...]] = {
    "industrial": INDUSTRIAL_AXES,
    "bank": BANK_AXES,
    "insurer": INSURER_AXES,
}


def axes_for(template: str) -> tuple[AxisSpec, ...]:
    return AXES_BY_TEMPLATE.get(template, ())


def component_score(value: Decimal | None, bad: Decimal, good: Decimal) -> Decimal | None:
    """Linear map of ``value`` from ``bad`` -> 1 to ``good`` -> 10, clamped to [1, 10]."""
    if value is None:
        return None
    raw = LOW + (value - bad) / (good - bad) * (HIGH - LOW)
    return max(LOW, min(HIGH, raw))


def axis_score(component_scores: Iterable[Decimal | None]) -> int | None:
    """Mean of the available component scores, rounded half up; ``None`` when none is available."""
    present = [s for s in component_scores if s is not None]
    if not present:
        return None
    mean = sum(present, D(0)) / len(present)
    return int(mean.quantize(D(1), rounding=ROUND_HALF_UP))
