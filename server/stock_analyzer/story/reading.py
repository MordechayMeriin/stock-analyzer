"""Report text for agents, under a per-agent token budget (design D2, task 5.4).

Each agent gets a :class:`ReadBudget`. The read tools charge the estimated tokens of what they
return and refuse a read that would overspend, telling the agent how much budget is left, so a
large business chapter fails visibly instead of being cut silently.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from stock_analyzer.ingest.parse_md import Paragraph, ParsedReport
from stock_analyzer.ingest.structure import Structure


class ReadRefused(ValueError):
    """A read the tool refuses; the message goes back to the agent."""


@dataclass
class ReadBudget:
    tokens: int
    chars_per_token: float
    spent: int = 0

    @property
    def remaining(self) -> int:
        return max(self.tokens - self.spent, 0)

    def estimate(self, text: str) -> int:
        return math.ceil(len(text) / max(self.chars_per_token, 0.1))

    def charge(self, text: str, what: str) -> str:
        cost = self.estimate(text)
        if cost > self.remaining:
            raise ReadRefused(
                f"reading {what} needs about {cost:,} tokens, but only {self.remaining:,} of this agent's "
                f"{self.tokens:,}-token reading budget are left; read fewer or smaller items"
            )
        self.spent += cost
        return text


def label(p: Paragraph) -> str:
    """A paragraph as agents see it: its id, its page and its text."""
    page = f"עמ' {p.page_printed}" if p.page_printed is not None else f"עמוד {p.page_index} בקובץ"
    return f"[{p.pid}] ({page})\n{p.text}"


@dataclass
class ReportLibrary:
    """The parsed reports of one story run, by fiscal year."""

    reports: Mapping[int, tuple[ParsedReport, Structure]]
    _paragraphs: dict[str, Paragraph] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for parsed, _ in self.reports.values():
            for p in parsed.paragraphs:
                self._paragraphs[p.pid] = p

    @property
    def paragraphs(self) -> Mapping[str, Paragraph]:
        return self._paragraphs

    def node_paragraphs(self, fiscal_year: int, node_id: str) -> list[Paragraph]:
        if fiscal_year not in self.reports:
            raise ReadRefused(f"FY{fiscal_year} is not one of this story's reports")
        parsed, structure = self.reports[fiscal_year]
        node = structure.node(node_id)
        if node is None:
            raise ReadRefused(f"no section {node_id!r} in the FY{fiscal_year} report")
        a, b = node.para_range
        return [p for p in parsed.paragraphs if a <= p.seq <= b]

    def outline(self, fiscal_year: int, chapter: str) -> str:
        """The section titles of one chapter, with node ids and pages (free: no budget charge)."""
        _, structure = self.reports[fiscal_year]
        lines = []
        for n in structure.nodes:
            if n.chapter == chapter and n.kind != "chapter":
                indent = "  " * max(n.level - 2, 0)
                number = f"{n.number} " if n.number else ""
                lines.append(f"{indent}{number}{n.title}  [{n.node_id}, pp. {n.pages[0]}-{n.pages[1]}]")
        return "\n".join(lines)


def read_section(library: ReportLibrary, budget: ReadBudget, fiscal_year: int, node_id: str) -> str:
    text = "\n\n".join(label(p) for p in library.node_paragraphs(fiscal_year, node_id))
    return budget.charge(text, f"section {node_id} of FY{fiscal_year}")


def read_paragraphs(library: ReportLibrary, budget: ReadBudget, paragraph_ids: Iterable[str]) -> str:
    ids = list(dict.fromkeys(paragraph_ids))
    missing = [i for i in ids if i not in library.paragraphs]
    if missing:
        raise ReadRefused(f"unknown paragraph ids: {', '.join(missing)}")
    text = "\n\n".join(label(library.paragraphs[i]) for i in ids)
    return budget.charge(text, f"{len(ids)} paragraphs")
