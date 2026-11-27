"""Evidence steps between finding verification and the scorecard (improve-osint-evidence design D3-D5).

Pure functions; the model calls (verifier, grouper) live in ``agents.py`` and pass their results here.

- Claim check: :func:`claim_batches` prepares the findings to check against the excerpt the run holds for
  their URL; :func:`apply_verdicts` drops unsupported findings and lowers partial and unverified ones.
- Duplicates: :func:`exact_duplicate_groups` finds near-identical findings from the same URL,
  :func:`validate_groups` cleans the groups a model proposes, :func:`merge_findings` merges each group into
  its strongest finding and renumbers the result.
- Trend: :func:`trend_hints` splits each area's findings into the last 12 months and older ones.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, timedelta

from rapidfuzz import fuzz

from stock_analyzer.osint.models import (
    AREAS,
    Area,
    KeptFinding,
    RunState,
    SourceRef,
    Verdict,
    normalize_url,
)
from stock_analyzer.osint.verify import parse_published

VERIFY_BATCH = 10
EXCERPT_CHARS = 3000
EXACT_DUPLICATE_RATIO = (
    90  # token_set_ratio; calibration: real duplicates from different articles score 63-71
)
RECENT_DAYS = 365

_VERDICT_RANK = {"supported": 0, "partial": 1, "unverified": 2}
_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}


# ---------------------------------------------------------------- claim check


def excerpt_for(state: RunState, finding: KeptFinding) -> str:
    hit = state.seen_urls.get(normalize_url(finding.source_url))
    return (hit.snippet if hit else "")[:EXCERPT_CHARS].strip()


def claim_batches(state: RunState, kept: list[KeptFinding]) -> list[list[dict[str, str]]]:
    """Findings that have an excerpt, as verifier inputs in batches of ``VERIFY_BATCH``."""
    items = [
        {"id": f.id, "claim": f.claim, "source_title": f.source_title, "excerpt": excerpt}
        for f in kept
        if (excerpt := excerpt_for(state, f))
    ]
    return [items[i : i + VERIFY_BATCH] for i in range(0, len(items), VERIFY_BATCH)]


def apply_verdicts(
    state: RunState, kept: list[KeptFinding], verdicts: Mapping[str, Verdict]
) -> tuple[list[KeptFinding], int]:
    """Findings with their verdicts, and how many were dropped as unsupported.

    No excerpt, or no verdict from the verifier, means ``unverified``; partial and unverified findings are
    kept at low confidence.
    """
    out: list[KeptFinding] = []
    unsupported = 0
    for f in kept:
        verdict = verdicts.get(f.id) if excerpt_for(state, f) else None
        if verdict == "unsupported":
            unsupported += 1
            continue
        kept_verdict = verdict or "unverified"
        update: dict[str, object] = {"verdict": kept_verdict}
        if kept_verdict != "supported":
            update["confidence"] = "low"
        out.append(f.model_copy(update=update))
    return out, unsupported


# ---------------------------------------------------------------- duplicates


def exact_duplicate_groups(kept: list[KeptFinding]) -> list[list[str]]:
    """Groups of findings with the same URL and near-identical claims."""
    groups: list[list[str]] = []
    for i, a in enumerate(kept):
        for b in kept[i + 1 :]:
            if normalize_url(a.source_url) == normalize_url(b.source_url) and (
                fuzz.token_set_ratio(a.claim, b.claim) >= EXACT_DUPLICATE_RATIO
            ):
                groups.append([a.id, b.id])
    return groups


def validate_groups(groups: Iterable[Iterable[str]], ids: Iterable[str]) -> list[list[str]]:
    """Only existing ids, each id in at most one group, groups of two or more."""
    known = set(ids)
    used: set[str] = set()
    out: list[list[str]] = []
    for group in groups:
        members = []
        for i in group:
            i = str(i).strip()
            if i in known and i not in used and i not in members:
                members.append(i)
        if len(members) >= 2:
            used.update(members)
            out.append(members)
    return out


def _strength(f: KeptFinding, order: int) -> tuple:
    published = parse_published(f.published_at) or date.min
    return (_VERDICT_RANK[f.verdict], _CONFIDENCE_RANK[f.confidence], -published.toordinal(), order)


def merge_findings(kept: list[KeptFinding], groups: Iterable[Iterable[str]]) -> tuple[list[KeptFinding], int]:
    """Merge each group of findings about the same event into its strongest one; renumber F1..Fn.

    Groups that share a finding are joined. Returns the findings in their original order (by the position of
    each representative) and how many findings were merged away.
    """
    order = {f.id: n for n, f in enumerate(kept)}
    by_id = {f.id: f for f in kept}
    parent = {f.id: f.id for f in kept}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for group in groups:
        members = [i for i in group if i in by_id]
        for other in members[1:]:
            parent[find(other)] = find(members[0])

    clusters: dict[str, list[KeptFinding]] = {}
    for f in kept:
        clusters.setdefault(find(f.id), []).append(f)

    merged_count = 0
    reps: list[KeptFinding] = []
    for members in clusters.values():
        rep = min(members, key=lambda f: _strength(f, order[f.id]))
        sources = {normalize_url(rep.source_url)}
        also_sources = list(rep.also_sources)
        also_areas = list(rep.also_areas)
        for f in members:
            if f is rep:
                continue
            merged_count += 1
            for ref in [SourceRef(url=f.source_url, title=f.source_title), *f.also_sources]:
                key = normalize_url(ref.url)
                if key not in sources:
                    sources.add(key)
                    also_sources.append(ref)
            for area in [f.area, *f.also_areas]:
                if area != rep.area and area not in also_areas:
                    also_areas.append(area)
        reps.append(rep.model_copy(update={"also_sources": also_sources, "also_areas": also_areas}))

    reps.sort(key=lambda f: order[f.id])
    return [f.model_copy(update={"id": f"F{n}"}) for n, f in enumerate(reps, 1)], merged_count


# ---------------------------------------------------------------- trend


def trend_hints(kept: list[KeptFinding], run_date: date) -> dict[Area, dict[str, int]]:
    """Per area: positive and negative findings from the last 12 months and from before, plus undated ones."""
    cutoff = run_date - timedelta(days=RECENT_DAYS)
    hints: dict[Area, dict[str, int]] = {
        area: {
            "recent_positive": 0,
            "recent_negative": 0,
            "older_positive": 0,
            "older_negative": 0,
            "undated": 0,
        }
        for area in AREAS
    }
    for f in kept:
        for area in [f.area, *f.also_areas]:
            h = hints[area]
            published = parse_published(f.published_at)
            if published is None:
                h["undated"] += 1
                continue
            period = "recent" if published >= cutoff else "older"
            if f.signal in ("positive", "negative"):
                h[f"{period}_{f.signal}"] += 1
    return hints
