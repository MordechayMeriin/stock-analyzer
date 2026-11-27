"""The story's fact registry: every number the story may show (company-story spec, design D3-D5).

Agents never write numbers. They cite facts by id, and code renders the values:

- ``FIN:<code>:<fy>``          a normalized financial value
- ``CHG:<code>:<fy0>-<fy1>``   the year-over-year change of a value or a core ratio
- ``RATIO:<code>:<fy>``        a core ratio
- ``TXT:<n>``                  a number quoted from a report paragraph, verified by code
- ``DER:<n>``                  a derived value from a closed set of operations
- ``WEB:<n>``                  a number quoted from a web source's excerpt, verified by code; always
                               low confidence (add-story-web-evidence)

Every fact records its inputs, so any number in a story can be traced to provider values or to
the paragraph it was quoted from, and carries the confidence of its weakest input.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation, localcontext
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from stock_analyzer.fin.canonical import fields_for
from stock_analyzer.fin.checks import failed_by_cell
from stock_analyzer.fin.normalize import decimal_str
from stock_analyzer.fin.ratios import GROUP_LABELS_HE
from stock_analyzer.ingest.parse_md import Paragraph
from stock_analyzer.story.web import WebSource

if TYPE_CHECKING:
    from stock_analyzer.services.ratios import Analysis

FactKind = Literal["FIN", "CHG", "RATIO", "TXT", "DER", "WEB"]
FactUnit = Literal["money", "percent", "pp", "multiple", "count", "per_share", "days", "number"]
Confidence = Literal["high", "low"]
Operation = Literal["pct_change", "ratio", "share", "sum", "diff"]

PRECISION = 28
OPERATIONS: tuple[Operation, ...] = ("pct_change", "ratio", "share", "sum", "diff")
WEB_CHECK = "web_source"  # the "failed check" every web fact carries: a press source, not audited


class Fact(BaseModel):
    fact_id: str
    kind: FactKind
    name_he: str
    unit: FactUnit
    years: list[int]
    value: str | None  # exact decimal string; percentages and points are fractions
    currency: str | None = None
    code: str | None = None  # line-item or ratio code
    inputs: list[str] = []  # fact ids (or line-item codes for FIN)
    operation: str | None = None  # DER: the operation; RATIO: the definition; TXT: "quote"
    source_filing_id: int | None = None
    paragraph_id: str | None = None  # TXT: where the number was quoted
    source_id: str | None = None  # WEB: the web source it was quoted from
    quote: str | None = None  # TXT / WEB: the exact quoted text
    reason: str | None = None  # why there is no value
    confidence: Confidence = "high"
    failed_checks: list[str] = []

    @property
    def decimal(self) -> Decimal | None:
        return Decimal(self.value) if self.value is not None else None


class FactError(ValueError):
    """A tool request the registry refuses; the message goes back to the agent."""


class FactRegistry:
    """The facts of one story run, keyed by id. Tools add ``TXT`` and ``DER`` facts."""

    def __init__(
        self,
        facts: Iterable[Fact] = (),
        paragraphs: Mapping[str, Paragraph] | None = None,
        currency: str | None = None,
    ):
        self._facts: dict[str, Fact] = {}
        self.paragraphs: Mapping[str, Paragraph] = paragraphs or {}
        self.currency = currency
        for f in facts:
            self.add(f)

    def __contains__(self, fact_id: object) -> bool:
        return fact_id in self._facts

    def __len__(self) -> int:
        return len(self._facts)

    def get(self, fact_id: str) -> Fact:
        try:
            return self._facts[fact_id]
        except KeyError:
            raise FactError(f"unknown fact id {fact_id!r}") from None

    def add(self, fact: Fact) -> Fact:
        self._facts[fact.fact_id] = fact
        return fact

    def facts(self) -> list[Fact]:
        return list(self._facts.values())

    def _content_id(self, kind: str, *parts: str) -> str:
        """A TXT/DER id derived from what the fact is, not from when it was made.

        Agents run in parallel, so a shared counter would number the same quote differently on
        every run; tool results, and with them the cache keys of later model turns, would change.
        A content-derived id keeps reruns replayable from the cache (design D8)."""
        digest = hashlib.sha256("\x1f".join((kind, *parts)).encode("utf-8")).hexdigest()
        return f"{kind}:{int(digest[:8], 16) % 100_000_000}"

    # -- derive (design D4)

    def derive(self, op: str, fact_ids: list[str]) -> Fact:
        """Apply a closed operation to registered facts and register the result."""
        if op not in OPERATIONS:
            raise FactError(f"unknown operation {op!r}; use one of {', '.join(OPERATIONS)}")
        facts = [self.get(i) for i in fact_ids]
        expected = {"pct_change": 2, "ratio": 2, "share": 2, "diff": 2}.get(op)
        if expected is not None and len(facts) != expected:
            raise FactError(f"{op} takes exactly {expected} fact ids (got {len(facts)})")
        if op == "sum" and len(facts) < 2:
            raise FactError("sum takes at least 2 fact ids")
        values = []
        for f in facts:
            if f.decimal is None:
                raise FactError(f"fact {f.fact_id} has no value ({f.reason or 'missing'})")
            values.append(f.decimal)
        units = {f.unit for f in facts}
        if op in ("sum", "diff", "share", "pct_change") and len(units) > 1:
            raise FactError(f"{op} needs facts in the same unit (got {', '.join(sorted(units))})")
        currencies = {f.currency for f in facts if f.currency}
        if len(currencies) > 1:
            raise FactError(f"facts are in different currencies: {', '.join(sorted(currencies))}")

        unit: FactUnit
        with localcontext() as ctx:
            ctx.prec = PRECISION
            if op == "sum":
                result, unit = sum(values, Decimal(0)), facts[0].unit
            elif op == "diff":
                result, unit = values[0] - values[1], facts[0].unit
            elif op in ("ratio", "share"):
                if values[1] == 0:
                    raise FactError(f"{facts[1].fact_id} is zero, so the {op} is undefined")
                result = values[0] / values[1]
                unit = "percent" if op == "share" else "multiple"
            else:  # pct_change: from the first fact to the second
                change, reason = percent_change(values[0], values[1])
                if change is None:
                    raise FactError(
                        f"no percent change from {facts[0].fact_id} to {facts[1].fact_id}: {reason}"
                    )
                result, unit = change, "percent"

        fact_id = self._content_id("DER", op, *fact_ids)
        if fact_id in self._facts:
            return self._facts[fact_id]
        failed = sorted({c for f in facts for c in f.failed_checks})
        low = any(f.confidence == "low" for f in facts)
        years = sorted({y for f in facts for y in f.years})
        names = " / ".join(f.name_he for f in facts)
        return self.add(
            Fact(
                fact_id=fact_id,
                kind="DER",
                name_he=f"{op}: {names}",
                unit=unit,
                years=years,
                value=decimal_str(result),
                currency=(next(iter(currencies), None) or self.currency) if unit == "money" else None,
                inputs=[f.fact_id for f in facts],
                operation=op,
                confidence="low" if low else "high",
                failed_checks=failed,
            )
        )

    # -- quote_number (design D5)

    def quote_number(self, paragraph_id: str, text: str, unit: str) -> Fact:
        """Register a number quoted verbatim from a report paragraph."""
        paragraph = self.paragraphs.get(paragraph_id)
        if paragraph is None:
            raise FactError(f"unknown paragraph id {paragraph_id!r}")
        quote = " ".join(text.split())
        haystack = " ".join(paragraph.text.split())
        at = haystack.find(quote)
        if not quote or at < 0:
            raise FactError(f"the text {text!r} does not appear in paragraph {paragraph_id}")
        value, parsed_unit = parse_quoted_number(
            quote, haystack[at + len(quote) : at + len(quote) + 20], haystack
        )
        if value is None:
            raise FactError(f"no number found in {text!r}")
        if unit not in ("money", "count", "percent", "number"):
            raise FactError("unit must be money, count, percent or number")
        if parsed_unit == "percent":
            unit = "percent"
        fact_id = self._content_id("TXT", paragraph_id, quote, unit)
        if fact_id in self._facts:
            return self._facts[fact_id]
        return self.add(
            Fact(
                fact_id=fact_id,
                kind="TXT",
                name_he=f"מצוטט מהדוח ({paragraph.fiscal_year})",
                unit=unit,  # type: ignore[arg-type]
                years=[paragraph.fiscal_year],
                value=decimal_str(value),
                currency=self.currency if unit == "money" else None,
                operation="quote",
                source_filing_id=paragraph.filing_id,
                paragraph_id=paragraph_id,
                quote=quote,
            )
        )

    # -- quote_web_number (add-story-web-evidence design D5)

    def quote_web_number(self, source: WebSource, text: str, unit: str) -> Fact:
        """Register a number quoted verbatim from a web source's excerpt (never a search summary)."""
        if unit not in ("money", "count", "percent", "number"):
            raise FactError("unit must be money, count, percent or number")
        if not source.excerpts:
            raise FactError(
                f"source {source.source_id} has no excerpt to quote from (it was stored before excerpts "
                "were kept); describe it without the number"
            )
        quote = " ".join(text.split())
        if not quote:
            raise FactError("empty quote")
        for raw in source.excerpts:
            haystack = " ".join(raw.split())
            at = haystack.find(quote)
            if at >= 0:
                break
        else:
            raise FactError(f"the text {text!r} does not appear in the excerpt of source {source.source_id}")
        before = haystack[max(0, at - 15) : at]
        after = haystack[at + len(quote) : at + len(quote) + 20]
        value, parsed_unit = parse_web_number(quote, after)
        if value is None:
            raise FactError(f"no number found in {text!r}")
        if parsed_unit == "percent":
            unit = "percent"
        currency = None
        if unit == "money":
            currency = detect_currency(before + " " + quote + " " + after)
            if currency is None:
                raise FactError(
                    f"no currency next to {text!r} in the excerpt; quote the amount with its currency "
                    '(₪, ש"ח, NIS, $, USD, €) or use another unit'
                )
        fact_id = self._content_id("WEB", source.source_id, quote, unit, currency or "")
        if fact_id in self._facts:
            return self._facts[fact_id]
        published = source.published
        return self.add(
            Fact(
                fact_id=fact_id,
                kind="WEB",
                name_he=f"מצוטט ממקור רשת: {source.title or source.url}",
                unit=unit,  # type: ignore[arg-type]
                years=[published.year] if published else [],
                value=decimal_str(value),
                currency=currency,
                operation="quote",
                source_id=source.source_id,
                quote=quote,
                confidence="low",
                failed_checks=[WEB_CHECK],
            )
        )


# ---------------------------------------------------------------- number parsing

_NUMBER = re.compile(r"\(?-?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?|\(?-?\d+(?:\.\d+)?\)?")
_SCALES = (("מיליארד", Decimal(1_000_000_000)), ("מיליון", Decimal(1_000_000)), ("אלף", Decimal(1_000)))
_TABLE_SCALES = (
    (re.compile(r"במיליוני|מיליוני ש"), Decimal(1_000_000)),
    (re.compile(r"באלפי|אלפי ש"), Decimal(1_000)),
)


def parse_quoted_number(quote: str, after: str, paragraph: str) -> tuple[Decimal | None, str | None]:
    """The first number in ``quote``, scaled by a scale word in or right after the quote, or by
    the paragraph's table header ("באלפי ש"ח"). Returns (value, "percent" or None)."""
    m = _NUMBER.search(quote)
    if not m:
        return None, None
    token = m.group(0)
    negative = token.startswith("(") and token.endswith(")")
    try:
        value = Decimal(token.strip("()").replace(",", ""))
    except InvalidOperation:
        return None, None
    if negative:
        value = -value
    rest = quote[m.end() :]
    if rest.lstrip().startswith("%") or (not rest.strip() and after.lstrip().startswith("%")):
        with localcontext() as ctx:
            ctx.prec = PRECISION
            return value / 100, "percent"
    nearby = rest + " " + after
    for word, factor in _SCALES:
        if re.match(rf"^\s*{word}", nearby):
            return value * factor, None
    for pattern, factor in _TABLE_SCALES:
        if pattern.search(paragraph) and "|" in paragraph:
            return value * factor, None
    return value, None


_WEB_SCALES = (
    (re.compile(r"^\s*(?:מיליארד|billion\b|bn\b|b\b)", re.IGNORECASE), Decimal(1_000_000_000)),
    (re.compile(r"^\s*(?:מיליון|million\b|mn\b|m\b)", re.IGNORECASE), Decimal(1_000_000)),
    (re.compile(r"^\s*(?:אלף|אלפי|thousand\b|k\b)", re.IGNORECASE), Decimal(1_000)),
)
_PERCENT_WORDS = re.compile(r"^\s*(?:%|אחוז|percent\b|per cent\b)", re.IGNORECASE)
_CURRENCIES = (
    ("ILS", re.compile(r'₪|ש["״]ח|שקל|\bNIS\b|\bILS\b', re.IGNORECASE)),
    ("USD", re.compile(r"\$|\bUSD\b|דולר", re.IGNORECASE)),
    ("EUR", re.compile(r"€|\bEUR\b|אירו|יורו", re.IGNORECASE)),
    ("GBP", re.compile(r"£|\bGBP\b|ליש\"ט", re.IGNORECASE)),
)


def parse_web_number(quote: str, after: str) -> tuple[Decimal | None, str | None]:
    """The first number in a web quote, scaled by a Hebrew or English scale word right after it.

    Unlike :func:`parse_quoted_number` there is no table-header scaling: an excerpt is loose text,
    so a stray "באלפי" elsewhere in it says nothing about this number."""
    m = _NUMBER.search(quote)
    if not m:
        return None, None
    token = m.group(0)
    negative = token.startswith("(") and token.endswith(")")
    try:
        value = Decimal(token.strip("()").replace(",", ""))
    except InvalidOperation:
        return None, None
    if negative:
        value = -value
    rest = quote[m.end() :]
    nearby = rest if rest.strip() else rest + " " + after
    if _PERCENT_WORDS.match(rest) or (not rest.strip() and _PERCENT_WORDS.match(after)):
        with localcontext() as ctx:
            ctx.prec = PRECISION
            return value / 100, "percent"
    for pattern, factor in _WEB_SCALES:
        if pattern.match(nearby):
            return value * factor, None
    return value, None


def detect_currency(window: str) -> str | None:
    """The one currency named in ``window``; None when there is none or more than one."""
    found = {code for code, pattern in _CURRENCIES if pattern.search(window)}
    return found.pop() if len(found) == 1 else None


# ---------------------------------------------------------------- building the registry
#
# Facts come from the financial-ratios engine (fin/canonical.py, fin/checks.py, fin/ratios.py):
# FIN facts are canonical sheet cells, RATIO facts are ratio values, and CHG facts are the
# year-over-year change of each cell (percent) and each ratio (the engine's own delta).

# canonical field kind -> fact unit
_FIELD_UNITS: dict[str, FactUnit] = {
    "amount": "money",
    "per_share": "per_share",
    "ratio": "multiple",
    "count": "count",
}
# ratio unit -> (fact unit, unit of its year-over-year change)
_RATIO_UNITS: dict[str, tuple[FactUnit, FactUnit]] = {
    "percent": ("percent", "pp"),
    "ratio": ("multiple", "multiple"),
    "amount": ("money", "percent"),
    "days": ("days", "days"),
}


def percent_change(old: Decimal | None, new: Decimal | None) -> tuple[Decimal | None, str | None]:
    """(new - old) / |old|, or no value with a reason: a missing year, a zero base, a sign change."""
    if old is None or new is None:
        return None, "a value is missing in one of the years"
    if old == 0:
        return None, "the previous value is zero"
    if (old < 0) != (new < 0) and new != 0:
        return None, "the sign changed between the years"
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return (new - old) / abs(old), None


def _input_fact(key: str, fiscal_year: int) -> str:
    """A ratio input key ("field", "opening:field", "prior:field") as the FIN fact it reads."""
    if ":" in key:
        kind, field = key.split(":", 1)
        return (
            f"FIN:{field}:{fiscal_year - 1}" if kind in ("opening", "prior") else f"FIN:{field}:{fiscal_year}"
        )
    return f"FIN:{key}:{fiscal_year}"


def registry_from_analysis(
    analysis: Analysis, years: list[int], paragraphs: Mapping[str, Paragraph] | None = None
) -> FactRegistry:
    """FIN, RATIO and CHG facts for the covered ``years`` (oldest first) from a ratios analysis."""
    sheet = analysis.sheet
    covered = sorted(set(years))
    pairs = list(zip(covered, covered[1:], strict=False))
    currency = analysis.currency
    labels = {f.name: f for f in fields_for(sheet.template)}
    failed = {fy: failed_by_cell(results) for fy, results in analysis.checks.items()}
    facts: list[Fact] = []

    def cell_fact(field: str, fy: int) -> Fact | None:
        cell = sheet.cell(fy, field)
        if cell is None or cell.value is None:
            return None
        spec = labels.get(field)
        unit = _FIELD_UNITS.get(spec.kind if spec else "amount", "money")
        checks = sorted(set(failed.get(fy, {}).get(field, [])))
        return Fact(
            fact_id=f"FIN:{field}:{fy}",
            kind="FIN",
            name_he=spec.label_he if spec else field,
            unit=unit,
            years=[fy],
            value=decimal_str(cell.value),
            currency=currency if unit in ("money", "per_share") else None,
            code=field,
            inputs=list(cell.inputs) or ([cell.source] if cell.source else []),
            operation=cell.source if cell.basis == "derived" else None,
            source_filing_id=cell.source_filing_id,
            confidence="low" if checks else "high",
            failed_checks=checks,
        )

    cells: dict[tuple[str, int], Fact] = {}
    for fy in covered:
        for field in sheet.fields:
            if (fact := cell_fact(field, fy)) is not None:
                cells[(field, fy)] = fact
                facts.append(fact)
    for field in sheet.fields:
        for y0, y1 in pairs:
            a, b = cells.get((field, y0)), cells.get((field, y1))
            if a is None and b is None:
                continue
            value, reason = percent_change(a.decimal if a else None, b.decimal if b else None)
            low = sorted({c for f in (a, b) if f for c in f.failed_checks})
            facts.append(
                Fact(
                    fact_id=f"CHG:{field}:{y0}-{y1}",
                    kind="CHG",
                    name_he=f"שינוי ב{(b or a).name_he}",  # type: ignore[union-attr]
                    unit="percent",
                    years=[y0, y1],
                    value=decimal_str(value) if value is not None else None,
                    code=field,
                    inputs=[f"FIN:{field}:{y0}", f"FIN:{field}:{y1}"],
                    reason=reason,
                    confidence="low" if low else "high",
                    failed_checks=low,
                )
            )

    for series in analysis.series:
        unit, change_unit = _RATIO_UNITS.get(series.unit, ("number", "number"))
        for fy in covered:
            v = series.values.get(fy)
            if v is None:
                continue
            facts.append(
                Fact(
                    fact_id=f"RATIO:{series.code}:{fy}",
                    kind="RATIO",
                    name_he=series.name_he,
                    unit=unit,
                    years=[fy],
                    value=decimal_str(v.value) if v.value is not None else None,
                    currency=currency if unit == "money" else None,
                    code=series.code,
                    inputs=[_input_fact(k, fy) for k in v.inputs],
                    operation=GROUP_LABELS_HE.get(series.group, series.group),
                    reason=v.missing_message_he or v.missing_reason,
                    confidence=v.confidence,
                    failed_checks=list(v.failed_checks),
                )
            )
        for y0, y1 in pairs:
            prev, cur = series.values.get(y0), series.values.get(y1)
            if cur is None:
                continue
            low = sorted({c for v in (prev, cur) if v for c in v.failed_checks})
            facts.append(
                Fact(
                    fact_id=f"CHG:{series.code}:{y0}-{y1}",
                    kind="CHG",
                    name_he=f"שינוי ב{series.name_he}",
                    unit=change_unit,
                    years=[y0, y1],
                    value=decimal_str(cur.delta) if cur.delta is not None else None,
                    code=series.code,
                    inputs=[f"RATIO:{series.code}:{y0}", f"RATIO:{series.code}:{y1}"],
                    reason=None if cur.delta is not None else "no comparable value in one of the years",
                    confidence="low" if low else "high",
                    failed_checks=low,
                )
            )
    return FactRegistry(facts, paragraphs, currency)
