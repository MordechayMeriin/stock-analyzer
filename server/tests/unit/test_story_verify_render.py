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


# ---------------------------------------------------------------- web facts (add-story-web-evidence)


def test_web_fact_renders_in_its_currency_with_a_press_caveat():
    usd = Fact(
        fact_id="WEB:1", kind="WEB", name_he="מצוטט ממקור רשת: Globes", unit="money", years=[2026],
        value="50000000", currency="USD", operation="quote", source_id="SRC:1", quote="$50 million",
        confidence="low", failed_checks=["web_source"],
    )  # fmt: skip
    reg = FactRegistry([usd])
    assert format_fact(usd) == "50.0 מיליון $"
    p = StoryParagraph(text_he="חוזה של {{WEB:1}}.", paragraph_ids=["p"], caveat_fact_ids=["WEB:1"])
    segments = render_paragraph(p, reg).segments
    assert segments[1].type == "fact" and segments[1].display == "50.0 מיליון $"
    caveat = segments[-1]
    assert caveat.type == "caveat" and "מקור עיתונאי, לא מבוקר" in caveat.text
    assert "בדיקות עקביות" not in caveat.text and "web_source" not in caveat.text


def test_existing_low_confidence_caveat_text_is_unchanged(registry):
    p = StoryParagraph(
        text_he="{{RATIO:free_cash_flow:2025}}",
        paragraph_ids=["MLTM-2025-p0010-005"],
        caveat_fact_ids=["RATIO:free_cash_flow:2025"],
    )
    caveat = render_paragraph(p, registry).segments[-1]
    assert caveat.text.startswith("נתונים בביטחון נמוך, כי נכשלו בדיקות עקביות בנתוני הספק:")
    assert "מקור עיתונאי" not in caveat.text


def test_web_tokens_are_recognised():
    assert tokens("a {{WEB:42}} b {{DER:7}}") == ["WEB:42", "DER:7"]


# ---------------------------------------------------------------- rules 7-10 (add-story-web-evidence)

from datetime import date  # noqa: E402

from stock_analyzer.story.web import SourceLedger, WebSource  # noqa: E402

TODAY = date(2026, 11, 26)
REPORT_PUBLISHED = date(2026, 3, 30)


def web_ledger() -> SourceLedger:
    def src(sid, published, derived=False):
        return WebSource(
            source_id=sid, url=f"https://news.example/{sid}", title=sid, excerpts=["e"],
            published_at=published, live=True, derived_from_filing=derived,
        )  # fmt: skip

    return SourceLedger(
        [
            src("SRC:1", "2026-06-01"),  # after the latest report, before as_of
            src("SRC:2", "2026-02-01"),  # before the latest report
            src("SRC:3", None),  # undated
            src("SRC:4", "2026-11-25"),  # after a past as_of
            src("SRC:5", "2026-07-01", derived=True),  # restates filings
        ]
    )


def check(registry, story, *, as_of=TODAY):
    errors = verify_story(
        story, registry, PIDS, YEARS,
        ledger=web_ledger(), as_of=as_of, today=TODAY, latest_report_published=REPORT_PUBLISHED,
    )  # fmt: skip
    return {(e.rule, e.where) for e in errors}, errors


def post_report(*sids, pids=()):
    return StoryParagraph(
        text_he='מנכ"ל החברה הודיע על פרישתו.', paragraph_ids=list(pids), source_ids=list(sids)
    )


def test_rule7_unknown_source(registry):
    story = good_story()
    story.what_changed[0].source_ids = ["SRC:99"]
    assert (7, "what_changed[0]") in check(registry, story)[0]
    story.what_changed[0].source_ids = ["SRC:1"]
    assert check(registry, story)[1] == []


def test_rule8_source_after_as_of(registry):
    story = good_story()
    story.what_changed[0].source_ids = ["SRC:4"]
    assert check(registry, story)[1] == []  # as_of today: fine
    assert (8, "what_changed[0]") in check(registry, story, as_of=date(2026, 10, 1))[0]


def test_rule8_undated_source_with_a_past_as_of(registry):
    story = good_story()
    story.what_changed[0].source_ids = ["SRC:3"]
    assert check(registry, story)[1] == []  # as_of today: undated is fine as extra evidence
    assert (8, "what_changed[0]") in check(registry, story, as_of=date(2026, 10, 1))[0]


def test_rule9_web_only_post_report_paragraph_passes(registry):
    story = good_story(what_changed=[*good_story().what_changed, post_report("SRC:1")])
    assert check(registry, story)[1] == []


def test_rule9_web_only_paragraph_before_the_report(registry):
    story = good_story(what_changed=[post_report("SRC:2")])
    assert (9, "what_changed[0]") in check(registry, story)[0]


def test_rule9_undated_source_alone(registry):
    story = good_story(what_changed=[post_report("SRC:3")])
    assert (9, "what_changed[0]") in check(registry, story)[0]


def test_web_only_what_it_does_is_rejected(registry):
    story = good_story(what_it_does=[post_report("SRC:1")])
    assert (3, "what_it_does[0]") in check(registry, story)[0]


def test_finding_with_web_sources_but_no_report_paragraph(registry):
    story = good_story()
    story.story_vs_numbers[0].paragraph_ids = []
    story.story_vs_numbers[0].source_ids = ["SRC:1"]
    assert (6, "story_vs_numbers[0]") in check(registry, story)[0]


def test_rule10_filing_derived_source_alone(registry):
    story = good_story(what_changed=[post_report("SRC:5")])
    assert (10, "what_changed[0]") in check(registry, story)[0]
    story = good_story()
    story.story_vs_numbers[0].source_ids = ["SRC:5", "SRC:1"]  # with an independent source
    assert check(registry, story)[1] == []


def test_web_citations_are_carried_into_rendering(registry):
    p = StoryParagraph(text_he="טקסט", paragraph_ids=["MLTM-2025-p0010-005"], source_ids=["SRC:1"])
    assert render_paragraph(p, registry).source_ids == ["SRC:1"]
    f = good_story().story_vs_numbers[0].model_copy(update={"source_ids": ["SRC:1"]})
    assert render_finding(f, registry).source_ids == ["SRC:1"]
