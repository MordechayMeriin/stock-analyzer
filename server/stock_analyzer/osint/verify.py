"""Checks that run in code, so they do not depend on the model following instructions (design D4-D5).

- :func:`verify_findings` keeps a finding only if its URL is not blocked, was returned by a search in this
  run, and its publish date (when known) is inside the window. Findings without a usable date are kept at
  low confidence.
- :func:`check_scorecard` makes every area, risk, strength and key driver cite kept findings, marks areas
  without findings as ``insufficient_data`` with trend ``unclear``, keeps at most three risks and
  strengths, and lists every key driver of the company profile (``unknown`` when nothing supports it).
"""

from __future__ import annotations

import calendar
import re
from collections import Counter
from datetime import date

from stock_analyzer.osint.models import (
    AREAS,
    DROP_REASONS,
    AreaAssessment,
    CompanyProfile,
    DropReason,
    KeptFinding,
    KeyDriver,
    Point,
    RunState,
    Scorecard,
    normalize_url,
)

_DATE = re.compile(r"^\s*(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?")


def parse_published(text: str | None) -> date | None:
    """The latest day a ``YYYY``, ``YYYY-MM`` or ``YYYY-MM-DD`` date can mean; None when unusable."""
    if not text:
        return None
    m = _DATE.match(text)
    if not m:
        return None
    year = int(m.group(1))
    month = int(m.group(2)) if m.group(2) else 12
    try:
        if m.group(3):
            return date(year, month, int(m.group(3)))
        return date(year, month, calendar.monthrange(year, month)[1])
    except ValueError:
        return None


def verify_findings(state: RunState) -> tuple[list[KeptFinding], dict[str, int]]:
    """Kept findings with ids F1, F2, ... and the number dropped per reason."""
    kept: list[KeptFinding] = []
    dropped: Counter[DropReason] = Counter()
    seen_claims: set[tuple[str, str]] = set()
    for area, report in state.reports:
        for finding in report.findings:
            url = normalize_url(finding.source_url)
            if state.blocklist.blocks(finding.source_url):
                dropped["blocked"] += 1
                continue
            if url not in state.seen_urls:
                dropped["not_searched"] += 1
                continue
            published = parse_published(finding.published_at)
            if published is not None and published < state.window_start:
                dropped["outside_window"] += 1
                continue
            key = (url, finding.claim.strip().lower())
            if key in seen_claims:  # the same fact reported twice (e.g. on a follow-up call)
                continue
            seen_claims.add(key)
            data = finding.model_dump()
            if published is None:
                data["confidence"] = "low"
                data["published_at"] = None
            kept.append(KeptFinding(**data, id=f"F{len(kept) + 1}", area=area))
    return kept, {reason: dropped.get(reason, 0) for reason in DROP_REASONS}


def check_scorecard(
    card: Scorecard, kept: list[KeptFinding], profile: CompanyProfile | None = None
) -> Scorecard:
    """A scorecard whose every claim cites kept findings, with one entry per area and per key driver."""
    by_id = {f.id: f for f in kept}
    by_area = {area: [f.id for f in kept if f.area == area or area in f.also_areas] for area in AREAS}

    given = {a.area: a for a in card.areas}
    areas: list[AreaAssessment] = []
    for area in AREAS:
        own = by_area[area]
        entry = given.get(area)
        importance = entry.importance if entry else "medium"
        if not own:
            areas.append(
                AreaAssessment(
                    area=area,
                    label="insufficient_data",
                    importance=importance,
                    assessment=entry.assessment if entry else "לא נמצאו ממצאים בתחום זה.",
                    trend="unclear",
                    trend_reason=entry.trend_reason if entry else "",
                    finding_ids=[],
                )
            )
            continue
        ids = [i for i in (entry.finding_ids if entry else []) if i in by_id]
        label = entry.label if entry and entry.label != "insufficient_data" else "watch"
        areas.append(
            AreaAssessment(
                area=area,
                label=label,
                importance=importance,
                assessment=entry.assessment if entry else "",
                trend=entry.trend if entry else "unclear",
                trend_reason=entry.trend_reason if entry else "",
                finding_ids=ids or own,
            )
        )

    def cited(points: list[Point]) -> list[Point]:
        out = []
        for p in points:
            ids = [i for i in p.finding_ids if i in by_id]
            if ids:
                out.append(Point(text=p.text, finding_ids=ids))
        return out[:3]

    drivers: list[KeyDriver] = []
    for d in card.key_drivers:
        ids = [i for i in d.finding_ids if i in by_id]
        drivers.append(
            KeyDriver(
                driver=d.driver,
                status=d.status if ids else "unknown",
                explanation=d.explanation,
                finding_ids=ids,
            )
        )
    if not drivers and profile:  # the model named no drivers: list the profile's, without evidence
        drivers = [
            KeyDriver(driver=n, status="unknown", explanation="", finding_ids=[]) for n in profile.key_drivers
        ]

    return Scorecard(
        overall_label=card.overall_label,
        overall_rationale=card.overall_rationale,
        overall_trend=card.overall_trend,
        overall_trend_reason=card.overall_trend_reason,
        key_drivers=drivers,
        areas=areas,
        risks=cited(card.risks),
        strengths=cited(card.strengths),
        summary_he=card.summary_he,
    )
