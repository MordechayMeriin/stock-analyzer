"""Normalized values → a template-specific canonical sheet, with per-cell provenance.

Each provider template (``industrial``, ``bank``, ``insurer``) has a fixed list of canonical fields. A field
is resolved, per fiscal year, from its sources in order, and the first that yields a value wins:

- :class:`Code`: a provider line-item code (the field's own code first, then fallback codes); basis
  ``reported``.
- :class:`CodeSum`: the sum of several provider codes, all of which must be present; basis ``derived``.
- :class:`Rule`: arithmetic over other canonical fields, all of which must have a value; basis ``derived``.
  ``embodies`` names the data-quality check whose identity the rule is (``fin/checks.py``), so that check
  is not counted as passed when it was used to fill the value.

Rules may depend on each other on purpose (gross profit ⇄ cost of revenue, total ⇄ common equity): a rule
that would recurse into a field already being resolved is skipped, so each one fills the other only when
the other is reported.

Pure: no I/O. ``services/ratios.py`` loads the values.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from stock_analyzer.errors import TemplateNotSupported
from stock_analyzer.fin.normalize import FinValue
from stock_analyzer.fin.normalize import as_of as filter_as_of

Basis = Literal["reported", "derived", "missing"]
Kind = Literal["amount", "per_share", "ratio", "count"]


@dataclass(frozen=True)
class Code:
    code: str


@dataclass(frozen=True)
class CodeSum:
    id: str
    codes: tuple[str, ...]


@dataclass(frozen=True)
class Rule:
    id: str
    inputs: tuple[str, ...]
    fn: Callable[..., Decimal]
    embodies: str | None = None  # data-quality check id this rule's identity is


Source = Code | CodeSum | Rule


@dataclass(frozen=True)
class Field:
    name: str
    statement: str  # income | balance_sheet | cash_flow | supplemental
    label_he: str
    sources: tuple[Source, ...]
    kind: Kind = "amount"


class Cell(BaseModel):
    field: str
    fiscal_year: int
    value: Decimal | None
    basis: Basis
    source: str | None = None  # provider code or rule id
    inputs: list[str] = []  # canonical fields (Rule) or provider codes (CodeSum)
    embodies: str | None = None
    source_filing_id: int | None = None
    source_filing_type: str | None = None
    available_at: datetime | None = None


class Sheet(BaseModel):
    template: str
    years: list[int]  # newest first
    fields: list[str]
    cells: dict[int, dict[str, Cell]]  # fiscal year → field → cell

    def cell(self, fiscal_year: int, field: str) -> Cell | None:
        return self.cells.get(fiscal_year, {}).get(field)

    def value(self, fiscal_year: int, field: str) -> Decimal | None:
        cell = self.cell(fiscal_year, field)
        return cell.value if cell else None


# -- field registries ---------------------------------------------------------------------------------


def _sub(a: Decimal, b: Decimal) -> Decimal:
    return a - b


def _add(a: Decimal, b: Decimal) -> Decimal:
    return a + b


def F(name: str, statement: str, label_he: str, *sources: Source, kind: Kind = "amount") -> Field:  # noqa: N802
    return Field(name, statement, label_he, tuple(sources), kind)


def C(*codes: str) -> tuple[Code, ...]:  # noqa: N802
    return tuple(Code(c) for c in codes)


# Shared by every template: totals, equity, net income, EPS and operating cash flow.
_EQUITY = (
    F("total_assets", "balance_sheet", "סך נכסים", *C("total_assets")),
    F("total_liabilities", "balance_sheet", "סך התחייבויות", *C("total_liabilities")),
    F("minority_interest", "balance_sheet", "זכויות שאינן מקנות שליטה", *C("minority_interest")),
    F(
        "total_equity",
        "balance_sheet",
        "סך הון",
        *C("total_equity"),
        Rule("equity_from_common", ("common_equity", "minority_interest"), _add, embodies="BS5"),
    ),
    F(
        "common_equity",
        "balance_sheet",
        "הון המיוחס לבעלי המניות",
        *C("total_common_equity"),
        Rule("common_from_equity", ("total_equity", "minority_interest"), _sub, embodies="BS5"),
    ),
)
_NET_INCOME = (
    F(
        "net_income_parent",
        "income",
        "רווח נקי לבעלי המניות",
        *C("net_income_loss"),
        Rule(
            "ni_parent_from_consolidated",
            ("net_income_consolidated", "minority_interest_in_earnings"),
            _sub,
            embodies="IS2",
        ),
    ),
    F(
        "net_income_consolidated",
        "income",
        "רווח נקי מאוחד",
        *C("consolidated_net_income"),
        Rule(
            "ni_consolidated_from_parent",
            ("net_income_parent", "minority_interest_in_earnings"),
            _add,
            embodies="IS2",
        ),
    ),
    F(
        "minority_interest_in_earnings",
        "income",
        "רווח המיוחס לזכויות שאינן מקנות שליטה",
        *C("minority_interest_in_earnings"),
    ),
    F("basic_eps", "income", "רווח בסיסי למניה", *C("basic_eps"), kind="per_share"),
)
_CFO = (F("cfo", "cash_flow", "תזרים מפעילות שוטפת", *C("cash_from_operations")),)

INDUSTRIAL: tuple[Field, ...] = (
    F("revenue", "income", "הכנסות", *C("revenue")),
    F(
        "cost_of_revenue",
        "income",
        "עלות ההכנסות",
        *C("cost_of_revenue"),
        Rule("cogs_from_gross_profit", ("revenue", "gross_profit"), _sub, embodies="IS1"),
    ),
    F(
        "gross_profit",
        "income",
        "רווח גולמי",
        *C("gross_profit"),
        Rule("gross_profit_from_cogs", ("revenue", "cost_of_revenue"), _sub, embodies="IS1"),
    ),
    F("operating_income", "income", "רווח תפעולי", *C("operating_income_loss")),
    F("ebit", "income", "EBIT", *C("ebit")),
    F(
        "d_and_a",
        "cash_flow",
        "פחת והפחתות",
        *C("depreciation_amortization_total_cf", "depreciation_and_amortization_supplemental"),
    ),
    F("ebitda", "income", "EBITDA", *C("ebitda"), Rule("ebitda_from_ebit", ("ebit", "d_and_a"), _add)),
    *_NET_INCOME,
    F("cash", "balance_sheet", "מזומנים ושווי מזומנים", *C("cash_and_equivalents")),
    F(
        "cash_and_st_investments",
        "balance_sheet",
        "מזומנים והשקעות לזמן קצר",
        *C("total_cash_and_short_term_investments"),
    ),
    F("receivables", "balance_sheet", "לקוחות וחייבים", *C("total_receivables", "accounts_receivable")),
    F("inventory", "balance_sheet", "מלאי", *C("inventory")),
    F("current_assets", "balance_sheet", "סך נכסים שוטפים", *C("total_current_assets")),
    F("current_liabilities", "balance_sheet", "סך התחייבויות שוטפות", *C("total_current_liabilities")),
    *_EQUITY,
    # Debt excludes lease liabilities, like the provider's total_debt_bs: on Malam FY2025 the reported
    # current (443,208,000) and non-current (241,424,000) debt equal these component sums exactly, while
    # capital_leases (26,244,000) is not part of either.
    F(
        "current_debt",
        "balance_sheet",
        "חוב לזמן קצר",
        *C("total_current_debt_bs"),
        CodeSum("current_debt_parts", ("short_term_borrowings", "current_portion_of_long_term_debt")),
    ),
    F("noncurrent_debt", "balance_sheet", "חוב לזמן ארוך", *C("total_non_current_debt_bs", "long_term_debt")),
    F(
        "total_debt",
        "balance_sheet",
        "סך חוב",
        *C("total_debt_bs"),
        Rule("debt_from_parts", ("current_debt", "noncurrent_debt"), _add, embodies="BS2"),
    ),
    F(
        "net_debt",
        "balance_sheet",
        "חוב נטו",
        *C("net_debt"),
        Rule("net_debt_from_debt", ("total_debt", "cash_and_st_investments"), _sub, embodies="BS3"),
    ),
    *_CFO,
    F("cfi", "cash_flow", "תזרים מפעילות השקעה", *C("cash_from_investing")),
    F("cff", "cash_flow", "תזרים מפעילות מימון", *C("cash_from_financing")),
    F("capex", "cash_flow", "השקעות ברכוש קבוע", *C("capital_expenditure_cf")),
    # Reported only: deriving it from CFO + CFI + CFF would hide the CF1 failures this data has.
    F("net_change_in_cash", "cash_flow", "שינוי נטו במזומנים", *C("net_change_in_cash_cf")),
    F("net_income_cf", "cash_flow", "רווח נקי (תזרים)", *C("net_income_cf")),
    F(
        "dividends_paid",
        "cash_flow",
        "דיבידנדים ששולמו",
        *C("total_dividends_paid_cf", "common_dividends_paid_cf"),
    ),
)

BANK: tuple[Field, ...] = (
    *_EQUITY,
    *_NET_INCOME,
    *_CFO,
    F(
        "cash_and_central_bank",
        "balance_sheet",
        "מזומנים ופיקדונות בבנקים מרכזיים",
        *C("cash_and_central_bank_balances", "cash_and_equivalents"),
    ),
    F("loans_net", "balance_sheet", "אשראי לציבור, נטו", *C("loans_to_customers_net")),
    F(
        "gross_loans",
        "balance_sheet",
        "אשראי לציבור, ברוטו",
        *C("gross_loans"),
        Rule("gross_loans_from_net", ("loans_net", "loan_loss_allowance"), _add),
    ),
    F("customer_deposits", "balance_sheet", "פיקדונות הציבור", *C("customer_deposits")),
    F("loan_loss_allowance", "balance_sheet", "הפרשה להפסדי אשראי", *C("loan_loss_allowance")),
    F("nonperforming_loans", "balance_sheet", "חובות פגומים", *C("nonperforming_loans")),
    F("risk_weighted_assets", "balance_sheet", "נכסי סיכון", *C("risk_weighted_assets")),
    F("cet1_ratio", "supplemental", "יחס הון עצמי רובד 1", *C("cet1_ratio"), kind="ratio"),
    F("tier1_ratio", "supplemental", "יחס הון רובד 1", *C("tier1_ratio"), kind="ratio"),
    F("total_capital_ratio", "supplemental", "יחס הון כולל", *C("total_capital_ratio"), kind="ratio"),
    F("leverage_ratio", "supplemental", "יחס מינוף", *C("leverage_ratio"), kind="ratio"),
)

INSURER: tuple[Field, ...] = (
    *_EQUITY,
    *_NET_INCOME,
    F("ebt", "income", "רווח לפני מס", *C("earnings_before_tax_including_unusual_items")),
    F("cash", "balance_sheet", "מזומנים ושווי מזומנים", *C("cash_and_equivalents")),
    *_CFO,
    F("cfi", "cash_flow", "תזרים מפעילות השקעה", *C("cash_from_investing")),
    F("cff", "cash_flow", "תזרים מפעילות מימון", *C("cash_from_financing")),
)

TEMPLATES: dict[str, tuple[Field, ...]] = {"industrial": INDUSTRIAL, "bank": BANK, "insurer": INSURER}


def fields_for(template: str | None) -> tuple[Field, ...]:
    if template is None:
        raise TemplateNotSupported(
            "the cached financials have no statement template (fetched before the provider added it); "
            "refetch them to compute ratios"
        )
    try:
        return TEMPLATES[template]
    except KeyError:
        raise TemplateNotSupported(f"no canonical fields for template {template!r}") from None


def field_def(template: str, name: str) -> Field:
    for f in fields_for(template):
        if f.name == name:
            return f
    raise KeyError(f"{template}: no canonical field {name!r}")


def _check_registry() -> None:
    """Every Rule input is a field of the same template; names are unique."""
    for template, fields in TEMPLATES.items():
        names = [f.name for f in fields]
        if len(names) != len(set(names)):
            raise ValueError(f"{template}: duplicate canonical field names")
        for f in fields:
            for src in f.sources:
                if isinstance(src, Rule) and not set(src.inputs) <= set(names):
                    raise ValueError(f"{template}.{f.name}: rule {src.id} uses unknown fields")


_check_registry()


# -- building -----------------------------------------------------------------------------------------


def _latest(stamps: Iterable[datetime | None]) -> datetime | None:
    stamps = list(stamps)
    if not stamps or any(s is None for s in stamps):
        return None
    return max(s for s in stamps if s is not None)


def _common(items: Iterable[object]) -> object | None:
    distinct = set(items)
    return distinct.pop() if len(distinct) == 1 else None


class _YearResolver:
    def __init__(self, fy: int, fields: dict[str, Field], reported: dict[str, FinValue]):
        self.fy = fy
        self.fields = fields
        self.reported = reported
        self.done: dict[str, Cell] = {}
        self.stack: set[str] = set()

    def resolve(self, name: str) -> Cell:
        if name in self.done:
            return self.done[name]
        self.stack.add(name)
        try:
            cell = self._first_source(self.fields[name])
        finally:
            self.stack.discard(name)
        self.done[name] = cell
        return cell

    def _first_source(self, field: Field) -> Cell:
        for src in field.sources:
            if isinstance(src, Code):
                v = self.reported.get(src.code)
                if v is not None:
                    return Cell(
                        field=field.name,
                        fiscal_year=self.fy,
                        value=v.value,
                        basis="reported",
                        source=src.code,
                        source_filing_id=v.source_filing_id,
                        source_filing_type=v.source_filing_type,
                        available_at=v.available_at,
                    )
            elif isinstance(src, CodeSum):
                parts = [self.reported.get(c) for c in src.codes]
                if all(p is not None for p in parts):
                    found = [p for p in parts if p is not None]
                    return self._derived(
                        field, src.id, list(src.codes), sum((p.value for p in found), Decimal(0)), found
                    )
            elif isinstance(src, Rule):
                if self.stack & set(src.inputs):
                    continue  # would recurse into a field being resolved (mutual rules)
                inputs = [self.resolve(n) for n in src.inputs]
                if all(c.value is not None for c in inputs):
                    value = src.fn(*(c.value for c in inputs))
                    cell = self._derived(field, src.id, list(src.inputs), value, inputs)
                    cell.embodies = src.embodies
                    return cell
        return Cell(field=field.name, fiscal_year=self.fy, value=None, basis="missing")

    def _derived(self, field: Field, source: str, inputs: list[str], value: Decimal, parts: list) -> Cell:
        return Cell(
            field=field.name,
            fiscal_year=self.fy,
            value=value,
            basis="derived",
            source=source,
            inputs=inputs,
            source_filing_id=_common(p.source_filing_id for p in parts),  # type: ignore[arg-type]
            source_filing_type=_common(p.source_filing_type for p in parts),  # type: ignore[arg-type]
            available_at=_latest(p.available_at for p in parts),
        )


def build_sheet(
    values: Iterable[FinValue], template: str | None, *, as_of: date | datetime | None = None
) -> Sheet:
    """The canonical sheet of one company: every template field in every fiscal year that has values.
    ``as_of`` keeps only values available at or before it (canonical-financials: Point-in-time)."""
    fields = fields_for(template)
    assert template is not None
    values = list(values)
    if as_of is not None:
        values = filter_as_of(values, as_of)
    by_year: dict[int, dict[str, FinValue]] = {}
    for v in values:
        by_year.setdefault(v.fiscal_year, {}).setdefault(v.code, v)
    field_map = {f.name: f for f in fields}
    cells: dict[int, dict[str, Cell]] = {}
    for fy, reported in by_year.items():
        resolver = _YearResolver(fy, field_map, reported)
        cells[fy] = {f.name: resolver.resolve(f.name) for f in fields}
    return Sheet(
        template=template,
        years=sorted(cells, reverse=True),
        fields=[f.name for f in fields],
        cells=cells,
    )
