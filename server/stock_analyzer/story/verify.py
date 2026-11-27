"""Story verification: numbers only as fact tokens, citations that exist, honest caveats (design D3).

Rules (each error names its rule and where in the story it is):

0. every section has content
1. every fact token parses and resolves to a fact with a value; every listed fact id resolves
2. no numerals outside tokens except the covered fiscal years, and no Hebrew number word next to
   a unit word ("כעשרה אחוזים")
3. every paragraph id exists in a covered year's report; story paragraphs cite at least one
4. every low-confidence fact an item cites is in that item's ``caveat_fact_ids``
5. a ``tension`` finding rests on at least one high-confidence fact
6. every finding cites at least one fact and one paragraph

Web evidence (add-story-web-evidence design D7):

7. every cited source id is in the run's source ledger
8. no cited source is dated after ``as_of``; when ``as_of`` is before today, none is undated
9. a story paragraph with no report paragraph is a what-changed paragraph whose sources are all
   dated after the latest report's publication and on or before ``as_of`` (the rule 3 exception)
10. an item's web sources are not all marked as restating the company's filings
"""

from __future__ import annotations

import re
from collections.abc import Container, Iterable
from datetime import date

from pydantic import BaseModel

from stock_analyzer.story.facts import FactError, FactRegistry
from stock_analyzer.story.models import Finding, Story, StoryParagraph
from stock_analyzer.story.web import SourceLedger

TOKEN = re.compile(r"\{\{\s*((?:FIN|CHG|RATIO):[A-Za-z0-9_]+:\d{4}(?:-\d{4})?|(?:TXT|DER|WEB):\d+)\s*\}\}")
_BRACES = re.compile(r"\{\{|\}\}")
_DIGITS = re.compile(r"\d+(?:[.,]\d+)*")

_NUMBER_WORDS = (
    "שניים|שתיים|שני|שתי|שלושה|שלוש|ארבעה|ארבע|חמישה|חמש|שישה|שש|שבעה|שבע|שמונה|תשעה|תשע|"
    "עשרה|עשר|עשרות|עשרים|שלושים|ארבעים|חמישים|שישים|שבעים|שמונים|תשעים|מאה|מאתיים|מאות|"
    "אלפים|אלף|אלפי|מיליון|מיליוני|מיליונים|מיליארד|מיליארדי|חצי|רבע|שליש|כפול|פי"
)
_UNIT_WORDS = (
    'אחוז|אחוזים|האחוזים|מיליון|מיליוני|מיליונים|מיליארד|מיליארדי|אלף|אלפי|ש"ח|שקל|שקלים|'
    'דולר|דולרים|נקודה|נקודות|נ"א'
)
QUANTITY_WORDS = re.compile(
    rf"(?<![א-ת])[וכבלמהש]{{0,3}}(?:{_NUMBER_WORDS})(?![א-ת])[\s\-־]+[וכבלמה]{{0,2}}(?:{_UNIT_WORDS})(?![א-ת])"
)


class VerificationError(BaseModel):
    rule: int
    where: str  # e.g. "what_changed[2]", "story_vs_numbers[0]"
    message: str


def tokens(text: str) -> list[str]:
    """Fact ids cited as tokens in ``text``, in order."""
    return [m.group(1) for m in TOKEN.finditer(text)]


def _items(story: Story) -> Iterable[tuple[str, StoryParagraph | Finding]]:
    for name in ("what_it_does", "what_changed", "story_vs_numbers"):
        for i, item in enumerate(getattr(story, name)):
            yield f"{name}[{i}]", item


def verify_story(
    story: Story,
    registry: FactRegistry,
    paragraph_ids: Container[str],
    years: Iterable[int],
    *,
    ledger: SourceLedger | None = None,
    as_of: date | None = None,
    today: date | None = None,
    latest_report_published: date | None = None,
) -> list[VerificationError]:
    """All rule violations in ``story``; an empty list means it may be saved and shown."""
    errors: list[VerificationError] = []
    allowed_years = {str(y) for y in years}
    ledger = ledger or SourceLedger()
    today = today or date.today()
    as_of = as_of or today

    def err(rule: int, where: str, message: str) -> None:
        errors.append(VerificationError(rule=rule, where=where, message=message))

    for name in ("what_it_does", "what_changed", "story_vs_numbers"):
        if not getattr(story, name):
            err(0, name, "the section is empty")

    for where, item in _items(story):
        text = item.text_he
        cited = tokens(text)
        listed = list(item.fact_ids) if isinstance(item, Finding) else []

        # rule 1: tokens and listed ids resolve to facts with values
        resolved = []
        for fact_id in dict.fromkeys(cited + listed):
            try:
                fact = registry.get(fact_id)
            except FactError:
                err(1, where, f"unknown fact {fact_id!r}")
                continue
            if fact.value is None:
                err(1, where, f"fact {fact_id} has no value ({fact.reason or 'missing'})")
            resolved.append(fact)
        stripped = TOKEN.sub(" ", text)
        if _BRACES.search(stripped):
            err(1, where, "a malformed fact token (use {{KIND:...}} exactly as the tools return it)")

        # rule 2: no numbers outside tokens
        for m in _DIGITS.finditer(stripped):
            if m.group(0) not in allowed_years:
                err(2, where, f"the numeral {m.group(0)!r} appears outside a fact token")
        for m in QUANTITY_WORDS.finditer(stripped):
            err(2, where, f"the quantity {m.group(0)!r} is written in words instead of a fact token")

        # rule 7: web sources resolve
        sources = []
        for sid in dict.fromkeys(item.source_ids):
            src = ledger.get(sid)
            if src is None:
                err(7, where, f"unknown web source {sid!r}")
            else:
                sources.append(src)

        # rule 8: no source after as_of; none undated when as_of is in the past
        for src in sources:
            if src.published is not None and src.published > as_of:
                err(8, where, f"web source {src.source_id} is dated {src.published_at}, after as_of {as_of}")
            elif src.published is None and as_of < today:
                err(
                    8,
                    where,
                    f"web source {src.source_id} has no publish date, and as_of {as_of} is in the past",
                )

        # rule 3: citations exist; story paragraphs must cite the report (rule 9 is the exception)
        for pid in item.paragraph_ids:
            if pid not in paragraph_ids:
                err(3, where, f"unknown paragraph id {pid!r}")
        if isinstance(item, StoryParagraph) and not item.paragraph_ids:
            if not where.startswith("what_changed") or not item.source_ids:
                err(3, where, "the paragraph cites no report paragraph")
            else:
                # rule 9: a web-only paragraph is about an event after the latest report
                for src in sources:
                    if src.published is None:
                        err(
                            9,
                            where,
                            f"web source {src.source_id} has no publish date, so it cannot stand alone",
                        )
                    elif latest_report_published is not None and src.published <= latest_report_published:
                        err(
                            9,
                            where,
                            f"web source {src.source_id} ({src.published_at}) is not after the latest report "
                            f"({latest_report_published}); cite the report for it",
                        )

        # rule 10: no circular corroboration
        if sources and all(src.derived_from_filing for src in sources):
            err(10, where, "its only web sources restate the company's own filings")

        # rule 4: low-confidence facts need a caveat
        caveats = set(item.caveat_fact_ids)
        for fact in resolved:
            if fact.confidence == "low" and fact.fact_id not in caveats:
                checks = ", ".join(fact.failed_checks) or "data checks"
                err(4, where, f"fact {fact.fact_id} has low confidence ({checks}) but no caveat")

        if isinstance(item, Finding):
            # rule 6: a finding rests on a fact and a paragraph
            if not resolved:
                err(6, where, "the finding cites no fact")
            if not item.paragraph_ids:
                err(6, where, "the finding cites no report paragraph")
            # rule 5: tension needs at least one high-confidence fact
            if item.label == "tension" and resolved and all(f.confidence == "low" for f in resolved):
                err(5, where, "a tension finding rests only on low-confidence facts")
    return errors


def text_errors(text: str, registry: FactRegistry, years: Iterable[int]) -> list[str]:
    """Rules 1 and 2 on one free-text field of a reader agent's output (design D2)."""
    allowed_years = {str(y) for y in years}
    problems = [f"unknown fact {fid!r}" for fid in tokens(text) if fid not in registry]
    stripped = TOKEN.sub(" ", text)
    problems += [
        f"numeral {m.group(0)!r}" for m in _DIGITS.finditer(stripped) if m.group(0) not in allowed_years
    ]
    problems += [f"quantity in words {m.group(0)!r}" for m in QUANTITY_WORDS.finditer(stripped)]
    return problems
