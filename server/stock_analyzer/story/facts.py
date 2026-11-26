"""The story's fact registry: every number the story may show (company-story spec, design D3-D5).

Agents never write numbers. They cite facts by id, and code renders the values:

- ``FIN:<code>:<fy>``          a normalized financial value
- ``CHG:<code>:<fy0>-<fy1>``   the year-over-year change of a value or a core ratio
- ``RATIO:<code>:<fy>``        a core ratio
- ``TXT:<n>``                  a number quoted from a report paragraph, verified by code
- ``DER:<n>``                  a derived value from a closed set of operations

Every fact records its inputs, so any number in a story can be traced to provider values or to
the paragraph it was quoted from, and carries the confidence of its weakest input.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation, localcontext
from typing import Literal

from pydantic import BaseModel

from stock_analyzer.fin.checks import CheckResult, failed_checks_for, run_checks
from stock_analyzer.fin.normalize import FinValue, check_currency, decimal_str
from stock_analyzer.fin.ratios import (
    RATIO_BY_CODE,
    Change,
    RatioValue,
    change_value,
    compute_changes,
    compute_ratios,
    fin_unit,
)
from stock_analyzer.ingest.parse_md import Paragraph

FactKind = Literal["FIN", "CHG", "RATIO", "TXT", "DER"]
FactUnit = Literal["money", "percent", "pp", "multiple", "count", "per_share", "number"]
Confidence = Literal["high", "low"]
Operation = Literal["pct_change", "ratio", "share", "sum", "diff"]

PRECISION = 28
OPERATIONS: tuple[Operation, ...] = ("pct_change", "ratio", "share", "sum", "diff")


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
    quote: str | None = None  # TXT: the exact quoted text
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
                change, reason = change_value(values[0], values[1], "percent")
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


# ---------------------------------------------------------------- building the registry


def build_registry(
    values: Iterable[FinValue],
    years: list[int],
    checks: list[CheckResult],
    ratios: Iterable[RatioValue],
    changes: Iterable[Change],
    paragraphs: Mapping[str, Paragraph] | None = None,
) -> FactRegistry:
    """FIN, RATIO and CHG facts for the covered ``years`` (oldest first)."""
    values = list(values)
    currency = check_currency(values)
    covered = set(years)
    facts: list[Fact] = []
    for v in values:
        if v.fiscal_year not in covered:
            continue
        failed = failed_checks_for([v.code], v.fiscal_year, checks)
        facts.append(
            Fact(
                fact_id=f"FIN:{v.code}:{v.fiscal_year}",
                kind="FIN",
                name_he=v.label,
                unit=fin_unit(v),
                years=[v.fiscal_year],
                value=decimal_str(v.value),
                currency=v.currency if fin_unit(v) in ("money", "per_share") else None,
                code=v.code,
                inputs=[v.code],
                source_filing_id=v.source_filing_id,
                confidence="low" if failed else "high",
                failed_checks=failed,
            )
        )
    for r in ratios:
        if r.fiscal_year not in covered:
            continue
        definition = RATIO_BY_CODE[r.code]
        facts.append(
            Fact(
                fact_id=f"RATIO:{r.code}:{r.fiscal_year}",
                kind="RATIO",
                name_he=r.name_he,
                unit=r.unit,
                years=[r.fiscal_year],
                value=r.value,
                currency=currency if r.unit == "money" else None,
                code=r.code,
                inputs=[f"FIN:{c}:{r.fiscal_year}" for c in definition.inputs],
                operation=definition.definition_he,
                reason=r.reason,
                confidence=r.confidence,
                failed_checks=r.failed_checks,
            )
        )
    for c in changes:
        if c.from_year not in covered or c.to_year not in covered:
            continue
        prefix = "FIN" if c.kind == "FIN" else "RATIO"
        facts.append(
            Fact(
                fact_id=f"CHG:{c.code}:{c.from_year}-{c.to_year}",
                kind="CHG",
                name_he=f"שינוי ב{c.name_he}",
                unit=c.unit,
                years=[c.from_year, c.to_year],
                value=c.value,
                code=c.code,
                inputs=[f"{prefix}:{c.code}:{c.from_year}", f"{prefix}:{c.code}:{c.to_year}"],
                reason=c.reason,
                confidence=c.confidence,
                failed_checks=c.failed_checks,
            )
        )
    return FactRegistry(facts, paragraphs, currency)


def registry_from_values(
    values: Iterable[FinValue],
    years: list[int],
    tolerances: Mapping[str, float],
    paragraphs: Mapping[str, Paragraph] | None = None,
) -> tuple[FactRegistry, list[CheckResult]]:
    """Run the checks, core ratios and changes on ``values`` and build the registry for ``years``.

    Ratios and changes use every year available, so the oldest covered year still gets its
    change from the year before when the provider has it; only covered years enter the registry.
    """
    values = list(values)
    checks = run_checks(values, tolerances)
    ratios = compute_ratios(values, checks)
    changes = compute_changes(values, ratios, checks)
    return build_registry(values, years, checks, ratios, changes, paragraphs), checks
