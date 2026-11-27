"""The rater: one agent that reads a saved story run and scores it (company-report spec, design D1).

Its input is the story as the analyst reads it (every number already rendered), the findings with
their labels, the profile, and the run's facts table. It has no tools: everything it may cite is in
the input, and verification checks every id it returns against the run's facts.
"""

from __future__ import annotations

import hashlib
import re

from agents import Agent

from stock_analyzer.config import Settings
from stock_analyzer.report.models import AXES, RaterOutput
from stock_analyzer.story.agents import ModelFactory, fact_line, prompt
from stock_analyzer.story.facts import FactRegistry
from stock_analyzer.story.pipeline import StoryRun
from stock_analyzer.story.render import RenderedParagraph, format_fact

PROMPT = "report_rater"
PURPOSE = "report.rater"
TOKEN = re.compile(r"\{\{([A-Z]+:[^{}]+)\}\}")


def prompt_hash(settings: Settings) -> str:
    return hashlib.sha256(prompt(settings, PROMPT).encode("utf-8")).hexdigest()


def rater_agent(settings: Settings, make_model: ModelFactory) -> Agent:
    return Agent(
        name="rater",
        instructions=prompt(settings, PROMPT),
        model=make_model("main", PURPOSE),
        tools=[],
        output_type=RaterOutput,
    )


def _paragraph_text(p: RenderedParagraph) -> str:
    return "".join((s.text or "") if s.type != "fact" else (s.display or "") for s in p.segments).strip()


def _fill_tokens(text: str, registry: FactRegistry) -> str:
    """Replace ``{{id}}`` tokens in saved text (the profile) with their display values."""

    def sub(m: re.Match[str]) -> str:
        fid = m.group(1)
        return format_fact(registry.get(fid)) if fid in registry else m.group(0)

    return TOKEN.sub(sub, text)


def rater_input(run: StoryRun) -> str:
    registry = FactRegistry(run.facts)
    parts: list[str] = [
        f"# Company {run.ticker}",
        f"Fiscal years to score (oldest first): {', '.join(str(y) for y in run.years)}",
        f"Axes, in order: {', '.join(a for a, _ in AXES)}",
        f"Story as of: {run.as_of}",
    ]
    if run.profile is not None and run.profile.items:
        parts.append("## Company profile")
        parts += [f"- ({i.topic}) {_fill_tokens(i.text_he, registry)}" for i in run.profile.items]
    parts.append("## What the company does")
    parts += [_paragraph_text(p) for p in run.rendered.what_it_does]
    parts.append("## What changed and why")
    parts += [_paragraph_text(p) for p in run.rendered.what_changed]
    parts.append("## Story vs numbers (findings)")
    parts += [f"- [{f.label}] {_paragraph_text(f)}" for f in run.rendered.story_vs_numbers]
    parts.append("## Facts table")
    parts += [fact_line(f) for f in run.facts]
    return "\n\n".join(parts)


def repair_input(base: str, previous: RaterOutput, errors: list[str]) -> str:
    return (
        base
        + "\n\n## Your previous answer\n\n"
        + previous.model_dump_json(indent=1)
        + "\n\n## Errors to fix\n\n"
        + "\n".join(f"- {e}" for e in errors)
    )
