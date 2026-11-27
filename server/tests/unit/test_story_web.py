"""The story's web source ledger, publish dates and the as_of filter (add-story-web-evidence)."""

from __future__ import annotations

from datetime import date

import pytest

from stock_analyzer.osint.models import KeptFinding, ResearchResult, Scorecard, SearchHit
from stock_analyzer.story.web import SourceLedger, find_publish_date, load_stored, source_id, within_as_of

TODAY = date(2026, 11, 26)


def kept(url: str, fid: str = "F1", published: str | None = "2026-10-01", **extra) -> KeptFinding:
    data = {
        "claim": "Maalot cut the rating", "signal": "negative", "confidence": "high", "source_url": url,
        "source_title": "Globes", "published_at": published, "derived_from_filing": False,
        "id": fid, "area": "credit", "excerpt": "Published 2026-10-01. The rating was cut.",
    } | extra  # fmt: skip
    return KeptFinding.model_validate(data)


def result(*findings: KeptFinding) -> ResearchResult:
    card = Scorecard(
        overall_label="watch",
        overall_rationale="r",
        overall_trend="stable",
        overall_trend_reason="r",
        key_drivers=[],
        areas=[],
        risks=[],
        strengths=[],
        summary_he="s",
    )
    return ResearchResult(
        ticker="MLTM", company_name="מלם", run_date=TODAY, window_months=36, window_start=date(2023, 11, 26),
        model="m", scorecard=card, findings=list(findings), dropped={}, searches_used=1, search_limit=40,
        cost_usd=None,
    )  # fmt: skip


# ---------------------------------------------------------------- ledger


def test_one_id_for_a_url_found_stored_and_live():
    ledger = SourceLedger()
    stored = ledger.add_stored(kept("https://www.globes.co.il/news/a/"))
    live = ledger.add_live(SearchHit("https://WWW.GLOBES.co.il/news/a", "Globes", "Another excerpt."), None)
    assert stored.source_id == live.source_id and len(ledger) == 1
    src = ledger.get(stored.source_id)
    assert src.stored and src.live and src.finding_id == "F1" and src.area == "credit"
    assert src.excerpts == ["Published 2026-10-01. The rating was cut.", "Another excerpt."]
    assert src.published_at == "2026-10-01"


def test_ids_are_stable_and_content_derived():
    url = "https://www.calcalist.co.il/x"
    assert source_id(url) == source_id(url + "/") == source_id(url + "#top")
    assert SourceLedger().add_live(SearchHit(url, "t", "s"), None).source_id == source_id(url)
    assert source_id(url).startswith("SRC:") and source_id(url) != source_id("https://other.example/x")


def test_live_excerpts_for_one_url_are_all_kept():
    ledger = SourceLedger()
    url = "https://www.themarker.com/a"
    ledger.add_live(SearchHit(url, "t", "first excerpt"), None)
    src = ledger.add_live(SearchHit(url, "t", "second excerpt"), date(2026, 5, 1))
    ledger.add_live(SearchHit(url, "t", "first excerpt"), None)  # a repeat is not stored twice
    assert src.excerpts == ["first excerpt", "second excerpt"] and src.published_at == "2026-05-01"


def test_derived_from_filing_is_kept_from_any_finding():
    ledger = SourceLedger()
    url = "https://www.bizportal.co.il/r"
    ledger.add_stored(kept(url, "F1"))
    src = ledger.add_stored(kept(url, "F2", derived_from_filing=True))
    assert src.derived_from_filing and src.finding_id == "F1"


# ---------------------------------------------------------------- publish dates


@pytest.mark.parametrize(
    ("title", "excerpt", "expected"),
    [
        ("", "פורסם 12.03.2026 עדכון על החברה", date(2026, 3, 12)),
        ("", "Published 2026-10-01. Example coverage.", date(2026, 10, 1)),
        ("", "12/03/2026 - המכרז הוכרע", date(2026, 3, 12)),
        ("", "ב-5 בנובמבר 2025 הודיעה החברה", date(2025, 11, 5)),
        ("", "On 3 March 2026 the company said", date(2026, 3, 3)),
        ("", "March 3, 2026 — the company said", date(2026, 3, 3)),
        ("Malam wins tender | Sep 9, 2025", "No date here.", date(2025, 9, 9)),
    ],
)
def test_date_formats(title, excerpt, expected):
    assert find_publish_date(title, excerpt, TODAY) == expected


def test_publication_word_beats_an_earlier_event_date():
    excerpt = "החוזה נחתם ב-01.02.2024 ויסתיים ב-31.12.2027. פורסם 12.03.2026"
    assert find_publish_date("", excerpt, TODAY) == date(2026, 3, 12)


def test_future_dates_are_ignored():
    assert find_publish_date("", "The contract runs to 31.12.2027.", TODAY) is None
    assert find_publish_date("", "Valid until 31.12.2027, signed 01.06.2026.", TODAY) == date(2026, 6, 1)


def test_undated_and_late_dates():
    assert find_publish_date("Malam news", "No date at all in this excerpt.", TODAY) is None
    late = "x" * 400 + " Published 2026-01-01"
    assert find_publish_date("", late, TODAY) is None  # only the start of an excerpt is read
    assert find_publish_date("", "31.02.2026 is not a day", TODAY) is None


# ---------------------------------------------------------------- the as_of filter


def test_within_as_of():
    past = date(2025, 11, 26)
    assert within_as_of(date(2025, 6, 1), past, TODAY)
    assert not within_as_of(date(2026, 1, 1), past, TODAY)  # after as_of
    assert not within_as_of(None, past, TODAY)  # undated, as_of in the past
    assert within_as_of(None, TODAY, TODAY)  # undated, as_of today


def test_load_stored_filters_by_as_of():
    findings = [
        kept("https://a.example/1", "F1", "2025-03-01"),
        kept("https://a.example/2", "F2", "2026-05-01"),  # after the past as_of
        kept("https://a.example/3", "F3", None),  # undated
    ]
    today_ledger = SourceLedger()
    assert load_stored(today_ledger, result(*findings), TODAY, TODAY) == 0 and len(today_ledger) == 3

    past_ledger = SourceLedger()
    assert load_stored(past_ledger, result(*findings), date(2025, 11, 26), TODAY) == 2
    assert [s.finding_id for s in past_ledger.stored()] == ["F1"]
