"""Business sections aligned across fiscal years, with a change status per year pair (design D6).

Deterministic and LLM-free. Sections are aligned by title, never by number (numbers drift
between years: risk factors were 25 in one TOC and 22 in the body). Each year's level-2
business sections are matched to the groups built so far: exact spelling-insensitive title keys
first, then fuzzy title matches, one-to-one and greedy by score. Inside each aligned section the
level-3 subsections are aligned the same way.

For each consecutive pair of years a section is ``unchanged`` when its text similarity is at or
above the threshold, ``changed`` below it, ``new`` when only the later year has it and
``dropped`` when only the earlier year has it. Numbers stay in the compared text, so a section
whose only edit is an updated figure counts as changed.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel
from rapidfuzz import fuzz

from stock_analyzer.ingest.parse_md import ParsedReport
from stock_analyzer.ingest.structure import Node, Structure, match_key

Status = Literal["unchanged", "changed", "new", "dropped"]

_NOT_LETTERS = re.compile(r"[^\w]|[\d_]")  # punctuation, digits and underscores
_PART_NUMBER = re.compile(r"^[א-ת]$")  # "חלק ב'" style part headings carry a letter, not a number
# two titles that agree on their first words are one section with different body words glued on;
# sibling segments ("פעילות החברה בתחום X" / "... Y") share only 3 of 5 words, so they stay apart
PREFIX_MIN_WORDS = 4
PREFIX_MIN_SHARE = 0.6


class PairStatus(BaseModel):
    from_year: int
    to_year: int
    status: Status
    similarity: float | None  # 0..1, rounded to 4 places; None for new / dropped


class AlignedSection(BaseModel):
    key: str  # stable within one comparison: "s3", or "s3.2" for a subsection
    title: str  # the latest year's title
    level: int  # 2 = section, 3 = subsection
    parent: str | None
    node_ids: dict[str, str]  # fiscal year -> node id, for the years where it appears
    pairs: list[PairStatus]


class Comparison(BaseModel):
    ticker: str
    years: list[int]  # oldest first
    unchanged_threshold: float
    sections: list[AlignedSection]  # pre-order: each section followed by its subsections


@dataclass
class Report:
    """One year's parsed report and structure, the input to :func:`compare_business`."""

    fiscal_year: int
    parsed: ParsedReport
    structure: Structure
    _texts: dict[str, str] = field(default_factory=dict)

    def text(self, node: Node) -> str:
        """The node's text, whitespace-normalized, without its own leading number: a section
        renumbered from 25 to 22 with identical text is unchanged."""
        if node.node_id not in self._texts:
            a, b = node.para_range
            parts = (p.text for p in self.parsed.paragraphs if a <= p.seq <= b)
            text = " ".join(" ".join(parts).split())
            if node.number:
                text = re.sub(rf"^\W*\.?{re.escape(node.number)}\.?\s*", "", text, count=1)
            self._texts[node.node_id] = text
        return self._texts[node.node_id]


def title_key(title: str) -> str:
    """Alignment key: spelling-insensitive, with numbers and punctuation ignored."""
    return " ".join(match_key(_NOT_LETTERS.sub(" ", title)).split())


def title_score(a: str, b: str) -> float:
    """0..100. Token-set matching tolerates extra words glued onto one title; the space-free ratio
    tolerates stray spaces inside words ("צ בר הזמנות"); a long common prefix tolerates different
    body words glued onto both ("…דיבידנדים חברות בנות" / "…דיבידנדים בחודש נובמ")."""
    ka, kb = title_key(a), title_key(b)
    if not ka or not kb:
        return 0.0
    score = max(fuzz.token_set_ratio(ka, kb), fuzz.ratio(ka.replace(" ", ""), kb.replace(" ", "")))
    ta, tb = ka.split(), kb.split()
    common = 0
    for x, y in zip(ta, tb, strict=False):
        if x != y:
            break
        common += 1
    if common >= PREFIX_MIN_WORDS and common >= PREFIX_MIN_SHARE * min(len(ta), len(tb)):
        score = max(score, 100.0)
    return score


def similarity(a: str, b: str) -> float:
    if a == b:
        return 1.0
    return round(fuzz.ratio(a, b) / 100, 4)


@dataclass
class _Group:
    nodes: dict[int, Node] = field(default_factory=dict)

    def latest(self) -> Node:
        return self.nodes[max(self.nodes)]


def _greedy(scored: list[tuple[float, int, int]], minimum: float) -> list[tuple[int, int]]:
    """One-to-one pairs (i, j), best score first, scores at or above ``minimum``."""
    pairs: list[tuple[int, int]] = []
    used_i: set[int] = set()
    used_j: set[int] = set()
    for score, i, j in sorted(scored, reverse=True):
        if score < minimum:
            break
        if i not in used_i and j not in used_j:
            pairs.append((i, j))
            used_i.add(i)
            used_j.add(j)
    return pairs


def _align(
    per_year: Sequence[tuple[int, list[Node]]],
    title_threshold: int,
    text_of: Callable[[int, Node], str],
    content_threshold: float,
) -> list[_Group]:
    groups: list[_Group] = []
    for year, nodes in per_year:
        open_groups = [g for g in groups if year not in g.nodes]
        unmatched = list(nodes)
        # 1. exact title keys, in document order (space-free, so stray spaces do not matter)
        for node in list(unmatched):
            key = title_key(node.title).replace(" ", "")
            hit = next(
                (g for g in open_groups if key and title_key(g.latest().title).replace(" ", "") == key), None
            )
            if hit is not None:
                hit.nodes[year] = node
                open_groups.remove(hit)
                unmatched.remove(node)
        # 2. fuzzy titles
        scored = [
            (title_score(n.title, g.latest().title), i, j)
            for i, n in enumerate(unmatched)
            for j, g in enumerate(open_groups)
        ]
        matched = _greedy(scored, title_threshold)
        # 3. same text under a garbled or reworded title
        left_i = [i for i in range(len(unmatched)) if i not in {a for a, _ in matched}]
        left_j = [j for j in range(len(open_groups)) if j not in {b for _, b in matched}]
        scored = [
            (
                similarity(
                    text_of(year, unmatched[i]), text_of(max(open_groups[j].nodes), open_groups[j].latest())
                ),
                i,
                j,
            )
            for i in left_i
            for j in left_j
        ]
        matched += _greedy(scored, content_threshold)
        for i, j in matched:
            open_groups[j].nodes[year] = unmatched[i]
        done = {i for i, _ in matched}
        for i, node in enumerate(unmatched):
            if i not in done:
                groups.append(_Group({year: node}))
    return groups


def _order(groups: list[_Group], years: list[int]) -> list[_Group]:
    """Latest-year document order; sections the latest year lacks go where they last appeared."""
    present = sorted(
        (g for g in groups if years[-1] in g.nodes), key=lambda g: g.nodes[years[-1]].para_range[0]
    )
    absent = [g for g in groups if years[-1] not in g.nodes]
    ordered = list(present)
    for g in sorted(absent, key=lambda g: (max(g.nodes), g.nodes[max(g.nodes)].para_range[0])):
        # place after the group that preceded it in the last year where it appeared
        year = max(g.nodes)
        start = g.nodes[year].para_range[0]
        before = [x for x in ordered if year in x.nodes and x.nodes[year].para_range[0] < start]
        pos = ordered.index(before[-1]) + 1 if before else 0
        ordered.insert(pos, g)
    return ordered


def _pairs(group: _Group, reports: dict[int, Report], years: list[int], threshold: float) -> list[PairStatus]:
    out: list[PairStatus] = []
    for y0, y1 in zip(years, years[1:], strict=False):
        a, b = group.nodes.get(y0), group.nodes.get(y1)
        if a is None and b is None:
            continue
        if a is None:
            out.append(PairStatus(from_year=y0, to_year=y1, status="new", similarity=None))
        elif b is None:
            out.append(PairStatus(from_year=y0, to_year=y1, status="dropped", similarity=None))
        else:
            score = similarity(reports[y0].text(a), reports[y1].text(b))
            status: Status = "unchanged" if score >= threshold else "changed"
            out.append(PairStatus(from_year=y0, to_year=y1, status=status, similarity=score))
    return out


def _business_sections(report: Report) -> list[Node]:
    """Level-2 business sections, without "חלק ב'" part headings: those group sections, hold
    almost no text, and only some years list them in the TOC."""
    return [
        n
        for n in report.structure.nodes
        if n.chapter == "business"
        and n.kind == "section"
        and n.level == 2
        and not (n.number and _PART_NUMBER.match(n.number))
        and "-part-" not in n.node_id
    ]


def _children(report: Report, node: Node) -> list[Node]:
    by_id = {n.node_id: n for n in report.structure.nodes}
    return [by_id[c] for c in node.children if c in by_id and by_id[c].level == 3]


def _merge_moved(
    children: list[tuple[int, _Group]],
    years: list[int],
    title_threshold: int,
    text_of: Callable[[int, Node], str],
    content_threshold: float,
) -> list[tuple[int, _Group]]:
    """Join a subsection that ends in year N with one, under another section, that starts in N+1.

    The joined subsection stays under the section where it appears last."""
    changed = True
    while changed:
        changed = False
        scored: list[tuple[float, int, int]] = []
        for a, (pa, ga) in enumerate(children):
            last = max(ga.nodes)
            if last == years[-1]:
                continue
            nxt = years[years.index(last) + 1]
            for b, (pb, gb) in enumerate(children):
                if pb == pa or min(gb.nodes) != nxt:
                    continue
                na, nb = ga.latest(), gb.nodes[nxt]
                if title_score(na.title, nb.title) >= title_threshold:
                    scored.append((2.0, a, b))  # a title match beats any text match
                else:
                    sim = similarity(text_of(last, na), text_of(nxt, nb))
                    if sim >= content_threshold:
                        scored.append((sim, a, b))
        for _, a, b in sorted(scored, reverse=True)[:1]:
            pa, ga = children[a]
            pb, gb = children[b]
            ga.nodes.update(gb.nodes)
            children[a] = (pb, ga)
            del children[b]
            changed = True
    return children


def compare_business(
    ticker: str,
    reports: Sequence[Report],
    *,
    unchanged_threshold: float,
    title_threshold: int,
    content_threshold: float,
) -> Comparison:
    """Align the business-description sections of ``reports`` (any order) and classify changes."""
    by_year = {r.fiscal_year: r for r in reports}
    years = sorted(by_year)

    def text_of(year: int, node: Node) -> str:
        return by_year[year].text(node)

    def align(per_year: Sequence[tuple[int, list[Node]]]) -> list[_Group]:
        return _align(per_year, title_threshold, text_of, content_threshold)

    sections = _order(align([(y, _business_sections(by_year[y])) for y in years]), years)

    # subsections: aligned inside each section, then merged across sections when one ends in a year
    # and a matching one starts in the next (a subsection moved, or a glued paragraph put it under
    # the neighbouring section in some years)
    children: list[tuple[int, _Group]] = []
    for i, group in enumerate(sections):
        child_years = [(y, _children(by_year[y], n)) for y, n in sorted(group.nodes.items())]
        children += [(i, c) for c in align(child_years)]
    children = _merge_moved(children, years, title_threshold, text_of, content_threshold)

    out: list[AlignedSection] = []
    for i, group in enumerate(sections):
        key = f"s{i + 1}"
        out.append(
            AlignedSection(
                key=key,
                title=group.latest().title,
                level=2,
                parent=None,
                node_ids={str(y): n.node_id for y, n in sorted(group.nodes.items())},
                pairs=_pairs(group, by_year, years, unchanged_threshold),
            )
        )
        mine = [c for parent, c in children if parent == i]
        child_order_years = sorted({y for c in mine for y in c.nodes} | set(group.nodes))
        for j, child in enumerate(_order(mine, child_order_years), 1):
            out.append(
                AlignedSection(
                    key=f"{key}.{j}",
                    title=child.latest().title,
                    level=3,
                    parent=key,
                    node_ids={str(y): n.node_id for y, n in sorted(child.nodes.items())},
                    pairs=_pairs(child, by_year, years, unchanged_threshold),
                )
            )
    return Comparison(ticker=ticker, years=years, unchanged_threshold=unchanged_threshold, sections=out)
