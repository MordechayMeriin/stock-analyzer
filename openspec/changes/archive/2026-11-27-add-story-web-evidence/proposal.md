# Proposal

## Why

The company story is written from the company's own annual reports only. It cannot see what happened after the latest report was published: a CEO leaving, a lost tender, a rating cut. It also cannot find an outside explanation for a move that management leaves unexplained. The OSINT research capability already collects cited, verified web findings for any tracked company, but the storyteller has no way to use them. This change gives the storyteller web evidence as tools, without weakening the project's ground rule that no LLM output becomes a number without a code check.

## What Changes

- **Web evidence tools for the storyteller.** Only the storyteller gets these tools. The describe, change and explain readers stay report-only.
  - `get_web_findings(area)`: reads the kept findings of the company's stored OSINT run, filtered to `as_of`. It is free.
  - `web_search(query)`: a live web search with the OSINT block-list and URL ledger, limited to 20 searches per story run. The limit is shared by the first attempt and the repair attempt.
  - `quote_web_number(source_id, text, unit)`: registers a number from a web source as a `WEB` fact, only if the text appears word for word in that source's excerpt, never in a search summary.
- **The story starts an OSINT run when the stored one is missing or stale.** When no stored OSINT run exists, or the stored one is older than 30 days (`STORY_OSINT_MAX_AGE_DAYS`), a live story run starts a normal OSINT research run. That run goes alongside the report readers and is stored as the latest OSINT result. If that run fails, the story continues with a warning.
- **Web citations inside the existing sections.** Story paragraphs and findings gain `source_ids` next to `paragraph_ids`. No new section is added.
  - `story_vs_numbers` findings still need a fact and a report paragraph, and web sources are only extra evidence there.
  - A `what_changed` paragraph may rest on web sources alone, but only for events dated after the latest report's publication date and on or before `as_of`.
- **Point-in-time web evidence.** No web source dated after `as_of` reaches the storyteller or the story. A `what_changed` paragraph cannot rest on an undated source alone.
- **`WEB` facts are always low confidence.** Every citation needs a caveat ("press source, not audited"), and a `tension` finding can never rest on them alone. A web number with no detectable currency is refused, so a dollar figure can never be shown as shekels.
- **No circular corroboration.** A source marked as derived from the company's filings cannot be a claim's only outside support.
- **Hard search cap.** A request for a 21st search fails the story run, and nothing is saved. The tool description states the limit, and every result reports the searches left.
- **Live searches are cached by (query, `as_of`).** A rerun for the same `as_of` replays its searches and model turns at no cost. A new `as_of` searches afresh.
- **OSINT findings keep their source excerpt.** Each kept finding stores the excerpt its search returned, so stored findings can be quoted. Stored results from before this change load without excerpts, and their numbers cannot be quoted.
- **Display.** The story page shows web citations as a separate kind of citation, with the source title, publish date and outbound link. `WEB` numbers show their source and the excerpt they were quoted from.

## Capabilities

### New Capabilities

None.

### Modified Capabilities
- `company-story`: adds the web evidence tools, `WEB` facts, web citations and their verification rules, the post-report rule for `what_changed`, the `as_of` filter, the search cap and search cache, starting an OSINT run when the stored one is missing or stale, and OSINT progress events. This capability is introduced by the in-flight change `company-story-agents`, which must be archived before this change.
- `osint-research`: kept findings store the source excerpt returned by their search.
- `analyzer-api`: the saved story includes its web sources, and a live story run is refused before streaming when an OSINT run for the company is already in progress. The story endpoints are introduced by `company-story-agents`.
- `web-client`: the story page shows web citations and the provenance of `WEB` numbers. The story view is introduced by `company-story-agents`.

## Impact

- **Server code:**
  - `story/agents.py`: new tools, storyteller input listing web findings, and `StoryContext` gains a web source ledger.
  - `story/facts.py`: the `WEB` fact kind and web number parsing (currency detection, English scale words, no table-header scaling).
  - `story/models.py`: `source_ids` on paragraphs and findings.
  - `story/verify.py`: new rules for web citations, `as_of`, the post-report window and circular corroboration.
  - `story/render.py`: the web caveat text and rendered web sources.
  - `story/pipeline.py`: loading and refreshing the OSINT run, running it in parallel, the search cap, and saved web sources in `StoryRun`.
  - `osint/models.py` and `osint/verify.py`: excerpts on kept findings.
  - `services/osint.py`: an async research entry point the story can await.
  - `config.py`: `STORY_MAX_SEARCHES` (20), `STORY_SEARCH_RESULTS`, `STORY_OSINT_MAX_AGE_DAYS` (30), and a higher `STORY_WRITER_MAX_TURNS`.
- **Prompts:** `story_storyteller.md` and `story_rules.md` describe the web tools and citation rules.
- **API contract:** the `StoryRun` schema gains web sources and `source_ids`. Regenerate `server/openapi.json` and `web/src/api/schema.d.ts`.
- **Web:** `StoryPage.tsx` gets web citation chips and `WEB` fact provenance.
- **Tests:** offline tests with `FakeSearch` and the fake agent models, covering web quotes, the verification rules, the search cap and cache, and the OSINT trigger.
- **Cost:** a live story may now also pay for an OSINT run (up to 40 searches plus its agents) when the stored one is missing or stale, plus up to 20 storyteller searches. A rerun on the same `as_of` is free.
- **Ordering:** `company-story-agents` must be archived first.
