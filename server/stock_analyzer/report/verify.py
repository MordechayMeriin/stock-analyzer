"""Checks on the rater's output before a report is built (company-report spec, design D3).

Every error is a plain sentence that goes back to the rater for its one repair turn.
"""

from __future__ import annotations

import re
from typing import get_args

from stock_analyzer.report.models import (
    AXES,
    MAX_DETAIL_TEXT,
    MAX_DRIVER,
    MAX_EVENT_SUMMARY,
    MAX_EVENT_TITLE,
    MAX_FACTORS,
    MAX_HEADLINE,
    MAX_SUMMARY,
    EventType,
    RaterOutput,
)
from stock_analyzer.story.facts import FactRegistry

DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH = re.compile(r"^\d{4}-\d{2}$")
EVENT_TYPES = set(get_args(EventType))


def _too_long(where: str, field: str, text: str | None, limit: int) -> list[str]:
    if text is not None and len(text) > limit:
        return [f"{where}: {field} is {len(text)} characters, the limit is {limit}"]
    return []


def verify_rating(out: RaterOutput, registry: FactRegistry, years: list[int]) -> list[str]:
    errors: list[str] = []
    errors += _too_long("summary", "summary", out.summary, MAX_SUMMARY)

    by_axis: dict[str, int] = {}
    for axis in out.axes:
        by_axis[axis.axis_id] = by_axis.get(axis.axis_id, 0) + 1
    for axis_id, _ in AXES:
        if by_axis.get(axis_id, 0) != 1:
            errors.append(f"axis {axis_id}: expected exactly one entry, got {by_axis.get(axis_id, 0)}")

    for axis in out.axes:
        seen = [y.fiscal_year for y in axis.years]
        for fy in years:
            if seen.count(fy) != 1:
                errors.append(
                    f"axis {axis.axis_id}: fiscal year {fy} must appear exactly once, got {seen.count(fy)}"
                )
        for fy in sorted(set(seen) - set(years)):
            errors.append(f"axis {axis.axis_id}: fiscal year {fy} is not one of the story's years {years}")
        for y in axis.years:
            where = f"axis {axis.axis_id} {y.fiscal_year}"
            if y.value is None:
                continue
            if not 1 <= y.value <= 10:
                errors.append(f"{where}: value {y.value} is outside 1-10 (use null when there is no basis)")
            if not y.evidence:
                errors.append(f"{where}: a score needs at least one evidence fact id")
            for fid in y.evidence:
                if fid not in registry:
                    errors.append(
                        f"{where}: unknown fact id {fid!r} in evidence; cite ids from the facts table"
                    )
            if not y.driver_label:
                errors.append(f"{where}: driver_label is missing")
            if not y.headline:
                errors.append(f"{where}: headline is missing")
            if not y.text:
                errors.append(f"{where}: text is missing")
            errors += _too_long(where, "driver_label", y.driver_label, MAX_DRIVER)
            errors += _too_long(where, "headline", y.headline, MAX_HEADLINE)
            errors += _too_long(where, "text", y.text, MAX_DETAIL_TEXT)
            if len(y.factors) > MAX_FACTORS:
                errors.append(f"{where}: {len(y.factors)} factors, the limit is {MAX_FACTORS}")
            for f in y.factors:
                if f.fact_id not in registry:
                    errors.append(f"{where}: unknown fact id {f.fact_id!r} in factor {f.label!r}")
                elif registry.get(f.fact_id).value is None:
                    errors.append(f"{where}: factor {f.label!r} cites {f.fact_id}, which has no value")

    for i, ev in enumerate(out.events):
        where = f"event {i + 1} ({ev.title})"
        if ev.type not in EVENT_TYPES:
            errors.append(f"{where}: unknown type {ev.type!r}")
        pattern = DAY if ev.date_precision == "day" else MONTH
        if not pattern.match(ev.date):
            errors.append(f"{where}: date {ev.date!r} does not match precision {ev.date_precision!r}")
        errors += _too_long(where, "title", ev.title, MAX_EVENT_TITLE)
        errors += _too_long(where, "summary", ev.summary, MAX_EVENT_SUMMARY)
    return errors
