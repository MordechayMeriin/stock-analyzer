"""Claim check, duplicate merging, trend hints and the company profile (improve-osint-evidence)."""

from __future__ import annotations

import asyncio
import json
from datetime import date

from stock_analyzer.osint import agents as agents_mod
from stock_analyzer.osint.agents import fake_model_factory, run_pipeline
from stock_analyzer.osint.blocklist import load_blocklist
from stock_analyzer.osint.evidence import (
    apply_verdicts,
    claim_batches,
    exact_duplicate_groups,
    merge_findings,
    trend_hints,
    validate_groups,
)
from stock_analyzer.osint.models import AREAS, KeptFinding, RunState, SearchHit
from stock_analyzer.osint.search import SNIPPET_CHARS, FakeSearch, parse_citations
from stock_analyzer.store import StoreLog, get_store

TODAY = date(2026, 11, 26)


def state_with(urls: dict[str, str]) -> RunState:
    state = RunState(
        ticker="ELAL",
        company_names=["אל על", "El Al Israel Airlines"],
        window_start=date(2023, 11, 26),
        blocklist=load_blocklist("ELAL"),
        max_searches=60,
        results_per_search=5,
    )
    state.seen_urls = {u: SearchHit(u, f"title {u}", snippet) for u, snippet in urls.items()}
    return state


def kf(
    id: str,
    url: str,
    claim: str,
    area: str = "news",
    *,
    verdict: str = "supported",
    confidence: str = "high",
    published: str | None = "2026-10-01",
    signal: str = "negative",
) -> KeptFinding:
    return KeptFinding(
        id=id,
        area=area,
        claim=claim,
        signal=signal,
        confidence=confidence,
        source_url=url,
        source_title=f"title {url}",
        published_at=published,
        derived_from_filing=False,
        verdict=verdict,
    )


# ---------------------------------------------------------------- excerpts and claim check


def test_search_keeps_longer_excerpts():
    message = {
        "annotations": [
            {
                "type": "url_citation",
                "url_citation": {"url": "https://a.example.com/x", "title": "t", "content": "x" * 5000},
            }
        ]
    }
    (hit,) = parse_citations(message)
    assert SNIPPET_CHARS == 3000 and len(hit.snippet) == 3000


def test_claim_batches_skip_findings_without_excerpt():
    state = state_with(
        {f"https://n.example.com/{i}": f"excerpt {i}" for i in range(12)} | {"https://empty.example.com/": ""}
    )
    kept = [kf(f"F{i}", f"https://n.example.com/{i}", f"claim {i}") for i in range(12)]
    kept.append(kf("F99", "https://empty.example.com/", "no excerpt"))
    batches = claim_batches(state, kept)
    assert [len(b) for b in batches] == [10, 2]
    assert all("F99" not in [i["id"] for i in b] for b in batches)
    assert batches[0][0]["excerpt"] == "excerpt 0"


def test_apply_verdicts():
    state = state_with(
        {"https://a.example.com/1": "x", "https://a.example.com/2": "x", "https://a.example.com/3": "x"}
    )
    kept = [
        kf("F1", "https://a.example.com/1", "supported claim"),
        kf("F2", "https://a.example.com/2", "partial claim"),
        kf("F3", "https://a.example.com/3", "invented figure"),
        kf("F4", "https://a.example.com/4", "no excerpt"),  # URL without an excerpt in the run
        kf("F5", "https://a.example.com/1", "left out by the verifier"),
    ]
    out, unsupported = apply_verdicts(state, kept, {"F1": "supported", "F2": "partial", "F3": "unsupported"})
    by_id = {f.id: f for f in out}
    assert unsupported == 1 and "F3" not in by_id
    assert by_id["F1"].verdict == "supported" and by_id["F1"].confidence == "high"
    assert by_id["F2"].verdict == "partial" and by_id["F2"].confidence == "low"
    assert by_id["F4"].verdict == "unverified" and by_id["F4"].confidence == "low"
    assert by_id["F5"].verdict == "unverified" and by_id["F5"].confidence == "low"


# ---------------------------------------------------------------- duplicates


FINE_121 = "On 8 February 2026 the Competition Authority proposed a NIS 121 million fine over wartime fares"
FINE_121_B = (
    "In February 2026 the Israel Competition Authority proposed a NIS 121 million fine for excessive fares"
)
FINE_110 = "The Competition Authority proposed a NIS 109.6 million fine over the aircraft-maintenance hangars"


def test_exact_pass_merges_only_same_url_near_identical():
    kept = [
        kf("F1", "https://g.example.com/a", FINE_121),
        kf("F2", "https://g.example.com/a/", FINE_121 + "."),  # same URL, same words
        kf("F3", "https://g.example.com/a", FINE_110),  # same URL, a different event
        kf("F4", "https://c.example.com/b", FINE_121_B),  # same event, other article: left to the grouper
    ]
    assert exact_duplicate_groups(kept) == [["F1", "F2"]]


def test_validate_groups():
    groups = [["F1", "F2"], ["F2", "F3"], ["F9", "F4"], ["F5"], ["F6", "F6", "F7"]]
    assert validate_groups(groups, ["F1", "F2", "F3", "F4", "F5", "F6", "F7"]) == [["F1", "F2"], ["F6", "F7"]]


def test_merge_keeps_strongest_and_lists_other_sources():
    kept = [
        kf(
            "F1",
            "https://c.example.com/fine",
            FINE_121,
            "labor_government",
            verdict="partial",
            confidence="low",
        ),
        kf("F2", "https://g.example.com/news", FINE_110, "news"),
        kf("F3", "https://g.example.com/fine", FINE_121_B, "news", published="2026-02-09"),
        kf("F4", "https://t.example.com/fine", FINE_121_B, "legal", published="2026-02-08"),
    ]
    merged, count = merge_findings(kept, [["F1", "F3"], ["F3", "F4"]])
    assert count == 2 and len(merged) == 2
    fine = next(f for f in merged if "121" in f.claim)
    assert fine.source_url == "https://g.example.com/fine"  # supported and newer beats partial and older
    assert {s.url for s in fine.also_sources} == {"https://c.example.com/fine", "https://t.example.com/fine"}
    assert set(fine.also_areas) == {"labor_government", "legal"}
    assert [f.id for f in merged] == ["F1", "F2"]  # renumbered in original order
    assert merged[0].claim == FINE_110 or merged[1].claim == FINE_110


def test_trend_hints():
    kept = [
        kf("F1", "u1", "a", "credit", published="2026-09-01", signal="negative"),
        kf("F2", "u2", "b", "credit", published="2024-03-01", signal="positive"),
        kf("F3", "u3", "c", "credit", published=None, signal="positive"),
        kf("F4", "u4", "d", "news", published="2026-11-01", signal="neutral").model_copy(
            update={"also_areas": ["credit"]}
        ),
    ]
    hints = trend_hints(kept, TODAY)
    assert set(hints) == set(AREAS)
    assert hints["credit"] == {
        "recent_positive": 0,
        "recent_negative": 1,
        "older_positive": 1,
        "older_negative": 0,
        "undated": 1,
    }


# ---------------------------------------------------------------- pipeline


def run(settings, factory, search=None, state=None):
    state = state or state_with({})
    state.seen_urls = {}
    out = asyncio.run(
        run_pipeline(
            settings,
            state,
            backend=search or FakeSearch(),
            log=StoreLog(get_store(settings), "llm"),
            model_factory=factory,
            today=TODAY,
        )
    )
    return out, state


def test_pipeline_drops_unsupported_and_marks_partial(settings):
    out, _ = run(
        settings, fake_model_factory("ELAL", verdicts={"news:": "unsupported", "market:": "partial"})
    )
    assert out.dropped["unsupported"] == 2  # both news findings
    assert all(f.area != "news" for f in out.findings)
    market = [f for f in out.findings if f.area == "market"]
    assert market and {(f.verdict, f.confidence) for f in market} == {("partial", "low")}


def test_pipeline_merges_duplicates_from_the_grouper(settings):
    search = FakeSearch(
        script={
            "ELAL news": [
                SearchHit("https://g.example.com/fine", "Fine NIS 121m", "Published 2026-02-09. fine")
            ],
            "ELAL legal": [
                SearchHit("https://c.example.com/fine", "Fine NIS 121m", "Published 2026-02-08. fine")
            ],
        }
    )
    factory = fake_model_factory("ELAL", groups=[["news: Fine NIS 121m", "legal: Fine NIS 121m"]])
    out, _ = run(settings, factory, search=search)
    assert out.merged == 1
    fines = [f for f in out.findings if "Fine NIS 121m" in f.claim]
    assert len(fines) == 1 and fines[0].also_sources and fines[0].also_areas
    assert [f.id for f in out.findings] == [f"F{n}" for n in range(1, len(out.findings) + 1)]


def test_pipeline_profile_and_fallback(settings):
    out, _ = run(settings, fake_model_factory("ELAL"))
    assert out.profile is not None and out.profile.industry
    assert out.scorecard.key_drivers
    assert {d.driver for d in out.scorecard.key_drivers} <= set(out.profile.key_drivers)

    out, _ = run(settings, fake_model_factory("ELAL", fail_orchestrator=True))
    assert out.profile is None  # the run still completes, with the drivers the synthesizer named
    assert out.findings and out.scorecard.key_drivers


def test_synthesizer_gets_profile_hints_and_merged_findings(settings):
    seen = {}

    class Spy(agents_mod.FakeAgentModel):
        async def get_response(self, system_instructions, input, *args, **kwargs):
            if self.role == "synthesizer":
                seen["payload"] = json.loads(agents_mod._user_text(agents_mod._items(input)))
            return await super().get_response(system_instructions, input, *args, **kwargs)

    run(settings, lambda role, area: Spy(role, area, "ELAL"))
    payload = seen["payload"]
    assert payload["profile"]["key_drivers"]
    assert set(payload["trend_hints"]) == set(AREAS)
    first = payload["findings"][0]
    assert {"verdict", "sources", "also_areas", "published_at"} <= set(first)


def test_verifier_and_grouper_usage_logged_on_cheap_model(settings):
    run(settings, fake_model_factory("ELAL"))
    records = [json.loads(line) for line in (settings.logs_dir / "llm.jsonl").read_text().splitlines()]
    by_purpose = {r["purpose"]: r for r in records}
    assert by_purpose["osint-agent:osint_verifier"]["model"] == settings.model_cheap
    assert by_purpose["osint-agent:osint_grouper"]["model"] == settings.model_cheap
    assert by_purpose["osint-agent:osint_synthesizer"]["model"] == settings.model_osint


def test_live_factory_uses_cheap_model_for_checks(settings):
    factory = agents_mod.live_model_factory(settings)
    assert factory("verifier", None).model == settings.model_cheap
    assert factory("grouper", None).model == settings.model_cheap
    assert factory("synthesizer", None).model == settings.model_osint
