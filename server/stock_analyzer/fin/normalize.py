"""Provider financial line items → typed, point-in-time ``FinValue`` records (plan.md §3.1).

- Values are exact ``Decimal``s in base units: ``raw_value × scale`` when the provider read the
  figure off the page (both set), else the provider's already-scaled ``value``. Never a float.
- One currency per company; a mismatch raises :class:`CurrencyMismatch` naming the items.
- Every value carries ``available_at`` (when the provider had it); :func:`as_of` keeps only
  values available at or before a date.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel

from stock_analyzer.errors import CurrencyMismatch, ParseError

Statement = Literal["income", "balance_sheet", "cash_flow", "supplemental"]

STATEMENTS: dict[str, Statement] = {
    "IS": "income",
    "BS": "balance_sheet",
    "CFS": "cash_flow",
    "SUP": "supplemental",
}
STATEMENT_ORDER: tuple[Statement, ...] = ("income", "balance_sheet", "cash_flow", "supplemental")
STATEMENT_LABELS_HE: dict[str, str] = {
    "income": "דוח רווח והפסד",
    "balance_sheet": "מאזן",
    "cash_flow": "דוח תזרימי מזומנים",
    "supplemental": "נתונים משלימים",
}

SCALES: dict[str, Decimal] = {
    "units": Decimal(1),
    "unit": Decimal(1),
    "ones": Decimal(1),
    "thousands": Decimal(1_000),
    "thousand": Decimal(1_000),
    "millions": Decimal(1_000_000),
    "million": Decimal(1_000_000),
    "billions": Decimal(1_000_000_000),
    "billion": Decimal(1_000_000_000),
}

# Hebrew display labels for the codes plan.md §3.1 uses; other codes fall back to the provider name.
LABELS_HE: dict[str, str] = {
    "revenue": "הכנסות",
    "cost_of_revenue": "עלות ההכנסות",
    "gross_profit": "רווח גולמי",
    "selling_general_administrative_expense": "הוצאות מכירה, הנהלה וכלליות",
    "research_development_expense": "הוצאות מחקר ופיתוח",
    "operating_income_loss": "רווח תפעולי",
    "ebit": "EBIT",
    "ebitda": "EBITDA",
    "net_interest_expense": "הוצאות מימון נטו",
    "earnings_before_tax_including_unusual_items": "רווח לפני מס",
    "income_tax_expense_benefit": "מסים על ההכנסה",
    "minority_interest_in_earnings": "רווח המיוחס לזכויות שאינן מקנות שליטה",
    "consolidated_net_income": "רווח נקי מאוחד",
    "net_income_loss": "רווח נקי לבעלי המניות",
    "basic_eps": "רווח בסיסי למניה",
    "diluted_eps": "רווח מדולל למניה",
    "cash_and_equivalents": "מזומנים ושווי מזומנים",
    "total_cash_and_short_term_investments": "מזומנים והשקעות לזמן קצר",
    "total_receivables": "לקוחות וחייבים",
    "accounts_receivable": "לקוחות",
    "inventory": "מלאי",
    "total_current_assets": "סך נכסים שוטפים",
    "total_assets": "סך נכסים",
    "accounts_payable": "ספקים",
    "total_current_liabilities": "סך התחייבויות שוטפות",
    "total_liabilities": "סך התחייבויות",
    "minority_interest": "זכויות שאינן מקנות שליטה",
    "total_common_equity": "הון המיוחס לבעלי המניות",
    "total_equity": "סך הון",
    "total_debt_bs": "סך חוב",
    "total_current_debt_bs": "חוב לזמן קצר",
    "total_non_current_debt_bs": "חוב לזמן ארוך",
    "net_debt": "חוב נטו",
    "net_income_cf": "רווח נקי (תזרים)",
    "cash_from_operations": "תזרים מפעילות שוטפת",
    "capital_expenditure_cf": "השקעות ברכוש קבוע",
    "cash_acquisitions_cf": "רכישות חברות",
    "cash_from_investing": "תזרים מפעילות השקעה",
    "cash_from_financing": "תזרים מפעילות מימון",
    "total_dividends_paid_cf": "דיבידנדים ששולמו",
    "net_change_in_cash_cf": "שינוי נטו במזומנים",
    "weighted_avg_basic_shares_outstanding": "ממוצע משוקלל של מניות",
    "shares_outstanding_on_filing_date": "מניות במחזור",
    "full_time_employees": "עובדים",
}


class FinValue(BaseModel):
    code: str
    label: str  # Hebrew label when known, else the provider's name
    statement: Statement
    fiscal_year: int
    value: Decimal  # exact, base units
    currency: str | None
    raw_value: Decimal | None  # as reported
    scale: str | None  # as reported
    available_at: datetime | None
    source_filing_id: int | None
    depth: int = 0
    sort_order: int = 0
    provider_value_differs: bool = False  # raw × scale disagreed with the provider's value

    @property
    def as_reported(self) -> bool:
        return self.raw_value is not None and self.scale is not None


def decimal_str(value: Decimal) -> str:
    """Canonical exact string: no exponent, no trailing zeros ("4138004000", "3.38")."""
    if value == value.to_integral_value():
        return format(value.quantize(Decimal(1)), "f")
    return format(value.normalize(), "f")


def _decimal(raw: Any, what: str) -> Decimal | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, float):
        raw = repr(raw)  # never route a float's binary value into Decimal
    try:
        return Decimal(str(raw))
    except InvalidOperation as exc:
        raise ParseError(f"{what}: not a decimal: {raw!r}") from exc


def _datetime(raw: Any) -> datetime | None:
    if not raw:
        return None
    dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def normalize_item(
    item: Mapping[str, Any],
    *,
    fiscal_year: int,
    statement_type: str,
    default_currency: str | None,
    source_filing_id: int | None,
) -> FinValue | None:
    """One line item as a FinValue, or None when the provider has no value for it."""
    code = item["code"]
    where = f"{code} FY{fiscal_year}"
    raw = _decimal(item.get("raw_value"), where)
    scale = item.get("scale")
    provider = _decimal(item.get("value"), where)
    differs = False
    if raw is not None and scale:
        multiplier = SCALES.get(str(scale).lower())
        if multiplier is None:
            raise ParseError(f"{where}: unknown scale {scale!r}")
        value = raw * multiplier
        differs = provider is not None and provider != value
    elif provider is not None:
        value = provider
    else:
        return None  # the provider lists the item without a value
    stype = item.get("statement_type") or statement_type
    return FinValue(
        code=code,
        label=LABELS_HE.get(code, item.get("name") or code),
        statement=STATEMENTS.get(stype, "supplemental"),
        fiscal_year=fiscal_year,
        value=value,
        currency=item.get("currency") or default_currency,
        raw_value=raw,
        scale=scale,
        available_at=_datetime(item.get("available_at")),
        source_filing_id=source_filing_id,
        depth=int(item.get("depth") or 0),
        sort_order=int(item.get("sort_order") or 0),
        provider_value_differs=differs,
    )


def normalize_financials(data: Mapping[str, Any], *, fiscal_period: str = "FY") -> list[FinValue]:
    """All line items of the provider's financials response, as FinValues. Raises
    :class:`CurrencyMismatch` if the company's values use more than one currency."""
    company_currency = (data.get("currency") or {}).get("code")
    values: list[FinValue] = []
    for period in data.get("periods", []):
        fy = period.get("fiscal_year")
        if fy is None or (period.get("fiscal_period") or fiscal_period) != fiscal_period:
            continue
        for st in period.get("statements", []):
            st_currency = (st.get("currency") or {}).get("code") or company_currency
            source = (st.get("source_filing") or {}).get("id")
            for item in st.get("line_items", []):
                value = normalize_item(
                    item,
                    fiscal_year=int(fy),
                    statement_type=st.get("statement_type", "SUP"),
                    default_currency=st_currency,
                    source_filing_id=source,
                )
                if value is not None:
                    values.append(value)
    check_currency(values)
    return values


def check_currency(values: Iterable[FinValue]) -> str | None:
    by_currency: dict[str, list[str]] = {}
    for v in values:
        if v.currency:
            by_currency.setdefault(v.currency, []).append(f"FY{v.fiscal_year} {v.code}")
    if len(by_currency) > 1:
        detail = "; ".join(
            f"{cur}: {', '.join(items[:4])}{' …' if len(items) > 4 else ''}"
            for cur, items in sorted(by_currency.items())
        )
        raise CurrencyMismatch(
            f"financial values use more than one currency ({', '.join(sorted(by_currency))}): {detail}"
        )
    return next(iter(by_currency), None)


def as_of(values: Iterable[FinValue], cutoff: date | datetime) -> list[FinValue]:
    """Values available at or before ``cutoff`` (a date means the end of that day, UTC).
    Values without an availability timestamp are excluded: their availability is unknown."""
    if isinstance(cutoff, datetime):
        limit = cutoff if cutoff.tzinfo else cutoff.replace(tzinfo=UTC)
    else:
        limit = datetime.combine(cutoff, time.max, tzinfo=UTC)
    return [v for v in values if v.available_at is not None and v.available_at <= limit]
