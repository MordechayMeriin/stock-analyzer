"""LLM tools over local data (analysis-tools spec).

:class:`AnalysisTools` is bound to one ticker and an optional ``as_of`` date when it is created; the model
cannot choose either. It exposes function-tool ``definitions`` in the form the LLM gateway forwards
(``llm.complete_json(..., tools=...)``) and executes calls with :meth:`AnalysisTools.call`.

- ``get_ratios(group?, codes?)``: ratio series with citable ids ``RATIO:{code}:{fy}``.
- ``get_financials(fields?)``: canonical values with citable ids ``FIN:{field}:{fy}``.

Results are compact JSON with decimal strings, built from the same service result and serializers as the
API (``services/ratios.py``), so the numbers match exactly. A bad argument returns ``{"error": ...}`` that
the model can read, instead of raising.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from typing import Any

from stock_analyzer.fin.canonical import fields_for
from stock_analyzer.fin.normalize import decimal_str
from stock_analyzer.fin.ratios import GROUP_LABELS_HE, RATIO_BY_CODE
from stock_analyzer.services.context import Ctx
from stock_analyzer.services.ratios import Analysis, analyze, value_out

DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_ratios",
            "description": (
                "Financial ratios of the company under analysis, per fiscal year (newest first). Values are "
                "decimal strings; percent ratios are fractions (0.1047 = 10.47%). Each value has an id to "
                "cite, a confidence (low when an input failed a data-quality check or was derived), the "
                "failed checks, and its change status from the year before. Never recompute these numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "group": {
                        "type": "string",
                        "enum": sorted(GROUP_LABELS_HE),
                        "description": "Only ratios of this group.",
                    },
                    "codes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Only these ratio codes, e.g. gross_margin, roe.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_financials",
            "description": (
                "Standardized financial values of the company under analysis, per fiscal year (newest "
                "first), in base units of the reporting currency, as decimal strings. Each value has an id "
                "to cite and its basis: reported, derived from other fields, or missing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Only these canonical fields, e.g. revenue, total_assets.",
                    }
                },
                "additionalProperties": False,
            },
        },
    },
]


class AnalysisTools:
    def __init__(self, ctx: Ctx, ticker: str, *, as_of: date | None = None):
        self.ctx = ctx
        self.ticker = ticker
        self.as_of = as_of
        self._analysis: Analysis | None = None

    @property
    def definitions(self) -> list[dict[str, Any]]:
        return DEFINITIONS

    @property
    def analysis(self) -> Analysis:
        """Computed once per tool set, on first use."""
        if self._analysis is None:
            self._analysis = analyze(self.ctx, self.ticker, as_of=self.as_of)
        return self._analysis

    def call(self, name: str, arguments: Mapping[str, Any] | str | None = None) -> dict[str, Any]:
        """Run one tool call. ``arguments`` may be the JSON string a model returns."""
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError as exc:
                return {"error": f"arguments are not valid JSON: {exc}"}
        args = dict(arguments or {})
        if name == "get_ratios":
            return self.get_ratios(group=args.get("group"), codes=args.get("codes"))
        if name == "get_financials":
            return self.get_financials(fields=args.get("fields"))
        return {"error": f"unknown tool {name!r}; available: get_ratios, get_financials"}

    def _header(self) -> dict[str, Any]:
        a = self.analysis
        return {
            "ticker": a.ticker,
            "template": a.template,
            "currency": a.currency,
            "as_of": a.as_of.isoformat() if a.as_of else None,
            "fiscal_years": a.years,
        }

    def get_ratios(self, group: str | None = None, codes: list[str] | None = None) -> dict[str, Any]:
        a = self.analysis
        available = {s.code: s for s in a.series}
        if group is not None and group not in GROUP_LABELS_HE:
            return {"error": f"unknown ratio group {group!r}; groups: {', '.join(sorted(GROUP_LABELS_HE))}"}
        for code in codes or []:
            if code not in available:
                why = (
                    "is not a ratio"
                    if code not in RATIO_BY_CODE
                    else f"does not apply to template {a.template}"
                )
                return {"error": f"ratio code {code!r} {why}; available: {', '.join(available)}"}
        selected = [
            s for s in a.series if (group is None or s.group == group) and (not codes or s.code in codes)
        ]
        ratios = []
        for s in selected:
            values = []
            for fy in a.years:
                v = value_out(s.values[fy])
                values.append(
                    {
                        "id": f"RATIO:{s.code}:{fy}",
                        "fy": fy,
                        "value": v.value,
                        "confidence": v.confidence,
                        "failed_checks": v.failed_checks,
                        "derived_inputs": v.derived_inputs,
                        "delta": v.delta,
                        "status": v.status,
                        "missing_reason": v.missing_reason,
                    }
                )
            ratios.append(
                {"code": s.code, "name_he": s.name_he, "group": s.group, "unit": s.unit, "values": values}
            )
        return {**self._header(), "ratios": ratios}

    def get_financials(self, fields: list[str] | None = None) -> dict[str, Any]:
        a = self.analysis
        defs = {f.name: f for f in fields_for(a.template)}
        for name in fields or []:
            if name not in defs:
                return {
                    "error": f"unknown field {name!r} for template {a.template}; fields: {', '.join(defs)}"
                }
        out = []
        for name in fields or list(defs):
            values = []
            for fy in a.years:
                cell = a.sheet.cell(fy, name)
                values.append(
                    {
                        "id": f"FIN:{name}:{fy}",
                        "fy": fy,
                        "value": decimal_str(cell.value)
                        if cell is not None and cell.value is not None
                        else None,
                        "basis": cell.basis if cell is not None else "missing",
                    }
                )
            out.append({"field": name, "label_he": defs[name].label_he, "values": values})
        return {**self._header(), "fields": out}
