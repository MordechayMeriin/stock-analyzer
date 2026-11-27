"""Story verification rules and rendering (company-story spec, design D3; tasks 5.5-5.6)."""

from __future__ import annotations

import pytest

from stock_analyzer.story.facts import Fact, FactRegistry, registry_from_analysis
from stock_analyzer.story.models import Finding, Story, StoryParagraph
from stock_analyzer.story.render import format_fact, render_finding, render_paragraph
from stock_analyzer.story.verify import QUANTITY_WORDS, tokens, verify_story
from tests.conftest import malam_analysis

YEARS = [2023, 2024, 2025]
PIDS = {"MLTM-2025-p0010-005", "MLTM-2024-p0066-001", "MLTM-2023-p0063-002"}


@pytest.fixture(scope="module")
def registry() -> FactRegistry:
    return registry_from_analysis(malam_analysis(), YEARS)


def good_story(**changes) -> Story:
    story = Story(
        what_it_does=[
            StoryParagraph(
                text_he="מלם תים היא קבוצת שירותי מחשוב; הכנסותיה בשנת 2025 הסתכמו ב-{{FIN:revenue:2025}}.",
                paragraph_ids=["MLTM-2025-p0010-005"],
            )
        ],
        what_changed=[
            StoryParagraph(
                text_he="ההכנסות צמחו ב-{{CHG:revenue:2024-2025}} ושיעור הרווח הגולמי היה {{RATIO:gross_margin:2025}}.",
                paragraph_ids=["MLTM-2024-p0066-001"],
            )
        ],
        story_vs_numbers=[
            Finding(
                label="consistent",
                text_he="ההנהלה מייחסת את הצמיחה לגידול בפעילות, והנתונים תומכים: {{CHG:revenue:2024-2025}}.",
                fact_ids=["CHG:revenue:2024-2025"],
                paragraph_ids=["MLTM-2025-p0010-005"],
            )
        ],
    )
    return story.model_copy(update=changes)


def rules(story: Story, registry: FactRegistry) -> list[int]:
    return [e.rule for e in verify_story(story, registry, PIDS, YEARS)]


def test_a_good_story_passes(registry):
    assert verify_story(good_story(), registry, PIDS, YEARS) == []


def test_rule0_empty_section(registry):
    assert 0 in rules(good_story(what_changed=[]), registry)


def test_rule1_unknown_token_and_fact_without_value(registry):
    bad = good_story(
        what_it_does=[
            StoryParagraph(text_he="הכנסות {{FIN:revenue:2031}}.", paragraph_ids=["MLTM-2025-p0010-005"])
        ]
    )
    assert rules(bad, registry) == [1]
    registry.add(
        Fact(
            fact_id="RATIO:empty:2025",
            kind="RATIO",
            name_he="ריק",
            unit="percent",
            years=[2025],
            value=None,
            reason="missing input",
        )
    )
    empty = good_story(
        what_it_does=[
            StoryParagraph(text_he="יחס {{RATIO:empty:2025}}.", paragraph_ids=["MLTM-2025-p0010-005"])
        ]
    )
    assert rules(empty, registry) == [1]


def test_rule1_malformed_token(registry):
    bad = good_story(
        what_it_does=[
            StoryParagraph(text_he="הכנסות {{FIN:revenue}}.", paragraph_ids=["MLTM-2025-p0010-005"])
        ]
    )
    assert 1 in rules(bad, registry)


def test_rule2_stray_numeral(registry):
    bad = good_story(
        what_it_does=[StoryParagraph(text_he="הכנסות של 4.1 מיליארד.", paragraph_ids=["MLTM-2025-p0010-005"])]
    )
    errors = verify_story(bad, registry, PIDS, YEARS)
    assert {e.rule for e in errors} == {2} and "'4.1'" in errors[0].message


def test_rule2_years_outside_the_story_are_numerals(registry):
    bad = good_story(
        what_it_does=[
            StoryParagraph(text_he="מאז שנת 2019 החברה גדלה.", paragraph_ids=["MLTM-2025-p0010-005"])
        ]
    )
    assert rules(bad, registry) == [2]


def test_rule2_quantity_in_words(registry):
    bad = good_story(
        what_it_does=[
            StoryParagraph(text_he="ההכנסות גדלו בכעשרה אחוזים.", paragraph_ids=["MLTM-2025-p0010-005"])
        ]
    )
    assert rules(bad, registry) == [2]
    assert QUANTITY_WORDS.search("עשרות מיליוני שקלים")
    assert not QUANTITY_WORDS.search("שלושה מגזרי פעילות")  # a count of things is fine


def test_rule3_unknown_or_missing_paragraph(registry):
    bad = good_story(what_it_does=[StoryParagraph(text_he="תיאור.", paragraph_ids=["MLTM-2025-p0999-001"])])
    assert rules(bad, registry) == [3]
    none = good_story(what_it_does=[StoryParagraph(text_he="תיאור.", paragraph_ids=[])])
    assert rules(none, registry) == [3]


def test_rule4_low_confidence_needs_a_caveat(registry):
    text = "התזרים החופשי היה {{RATIO:free_cash_flow:2025}}."
    bad = good_story(what_changed=[StoryParagraph(text_he=text, paragraph_ids=["MLTM-2024-p0066-001"])])
    errors = verify_story(bad, registry, PIDS, YEARS)
    assert [e.rule for e in errors] == [4] and "CF1" in errors[0].message
    ok = good_story(
        what_changed=[
            StoryParagraph(
                text_he=text,
                paragraph_ids=["MLTM-2024-p0066-001"],
                caveat_fact_ids=["RATIO:free_cash_flow:2025"],
            )
        ]
    )
    assert verify_story(ok, registry, PIDS, YEARS) == []


def test_rule5_tension_on_weak_data(registry):
    weak = Finding(
        label="tension",
        text_he="ההנהלה מדברת על שיפור בתזרים, אך {{RATIO:free_cash_flow:2025}}.",
        fact_ids=["RATIO:free_cash_flow:2025"],
        paragraph_ids=["MLTM-2025-p0010-005"],
        caveat_fact_ids=["RATIO:free_cash_flow:2025"],
    )
    assert rules(good_story(story_vs_numbers=[weak]), registry) == [5]


def test_rule6_finding_without_fact_or_paragraph(registry):
    no_fact = Finding(
        label="unexplained", text_he="אין הסבר.", fact_ids=[], paragraph_ids=["MLTM-2025-p0010-005"]
    )
    assert rules(good_story(story_vs_numbers=[no_fact]), registry) == [6]
    no_para = Finding(label="consistent", text_he="{{FIN:revenue:2025}}.", fact_ids=[], paragraph_ids=[])
    assert rules(good_story(story_vs_numbers=[no_para]), registry) == [6]


def test_tokens_are_extracted_in_order():
    assert tokens("א {{FIN:revenue:2025}} ב {{ CHG:revenue:2024-2025 }} ג {{DER:3}}") == [
        "FIN:revenue:2025",
        "CHG:revenue:2024-2025",
        "DER:3",
    ]


# ---------------------------------------------------------------- rendering


def test_display_formats(registry):
    assert format_fact(registry.get("FIN:revenue:2025")) == "4,138 מיליון ₪"
    assert format_fact(registry.get("RATIO:free_cash_flow:2025")) == "65.5 מיליון ₪"
    assert format_fact(registry.get("RATIO:gross_margin:2025")) == "10.47%"
    assert format_fact(registry.get("CHG:revenue:2024-2025")) == "+9.43%"
    assert format_fact(registry.get("RATIO:current_ratio:2025")) == "1.18"
    pp = registry.get("CHG:gross_margin:2024-2025")
    assert pp.unit == "pp" and format_fact(pp) == '-0.13 נ"א'


def test_render_paragraph_segments(registry):
    rendered = render_paragraph(good_story().what_it_does[0], registry)
    kinds = [s.type for s in rendered.segments]
    assert kinds == ["text", "fact", "text"]
    fact = rendered.segments[1]
    assert fact.fact_id == "FIN:revenue:2025" and fact.display == "4,138 מיליון ₪"
    assert rendered.paragraph_ids == ["MLTM-2025-p0010-005"]


def test_caveat_is_written_by_code(registry):
    p = StoryParagraph(
        text_he="התזרים החופשי היה {{RATIO:free_cash_flow:2025}}.",
        paragraph_ids=["MLTM-2024-p0066-001"],
        caveat_fact_ids=["RATIO:free_cash_flow:2025"],
    )
    caveat = render_paragraph(p, registry).segments[-1]
    assert caveat.type == "caveat" and caveat.fact_ids == ["RATIO:free_cash_flow:2025"]
    assert "CF1" in caveat.text and "ביטחון נמוך" in caveat.text


def test_render_finding_keeps_label_and_facts(registry):
    f = render_finding(good_story().story_vs_numbers[0], registry)
    assert f.label == "consistent" and f.fact_ids == ["CHG:revenue:2024-2025"]
    assert any(s.display == "+9.43%" for s in f.segments)
