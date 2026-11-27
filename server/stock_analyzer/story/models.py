"""The storyteller's output schema (design D2). Text fields hold Hebrew prose with fact tokens."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

FindingLabel = Literal["consistent", "tension", "unexplained"]


class StoryParagraph(BaseModel):
    text_he: str = Field(
        description="Hebrew prose. Quantities only as fact tokens such as {{FIN:revenue:2025}}."
    )
    paragraph_ids: list[str] = Field(description="Report paragraph ids this paragraph draws on.")
    source_ids: list[str] = Field(
        default_factory=list, description="Web source ids (SRC:...) this paragraph draws on, if any."
    )
    caveat_fact_ids: list[str] = Field(
        default_factory=list, description="Low-confidence facts this paragraph cites; code writes the caveat."
    )


class Finding(BaseModel):
    label: FindingLabel
    text_he: str = Field(
        description="Hebrew prose with fact tokens: how the story fits (or not) the numbers."
    )
    fact_ids: list[str] = Field(description="Facts the finding rests on (tokens in the text count too).")
    paragraph_ids: list[str] = Field(description="Report paragraphs the finding rests on.")
    source_ids: list[str] = Field(
        default_factory=list, description="Web source ids (SRC:...) cited as additional evidence, if any."
    )
    caveat_fact_ids: list[str] = Field(default_factory=list)


class Story(BaseModel):
    what_it_does: list[StoryParagraph] = Field(description="What the company does, from the latest report.")
    what_changed: list[StoryParagraph] = Field(description="What changed across the covered fiscal years.")
    story_vs_numbers: list[Finding] = Field(description="How management's story fits the numbers.")
