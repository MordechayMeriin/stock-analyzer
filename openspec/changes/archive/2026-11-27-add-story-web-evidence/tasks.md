# Tasks

## 1. Preconditions and settings

- [x] 1.1 Confirm the story and OSINT code this change builds on is on `main` (merged from `company-story-agents` and `add-osint-research`) and start from a branch; verify `server/stock_analyzer/story/` and `server/stock_analyzer/osint/` exist, the server test suite passes on the branch, and `openspec validate add-story-web-evidence` passes (archive order is in the workflow follow-up)
- [x] 1.2 Add `story_max_searches` (20), `story_search_results` (5) and `story_osint_max_age_days` (30) to `config.py` with environment overrides, raise `story_writer_max_turns` to 40, and document them in `server/README.md`; verify `test_config.py` covers the defaults and overrides and that `_config_hash_from` changes when each one changes

## 2. OSINT: excerpts and an async entry point

- [x] 2.1 Add `excerpt: str | None = None` to `KeptFinding` and fill it in `verify_findings` from the URL's search hit (design D6); verify `test_osint_agents.py` / `test_osint_models.py` show kept findings carrying the `FakeSearch` excerpt, and a stored result JSON without `excerpt` still loads
- [x] 2.2 Factor the block-list, ledger and usage-log core out of `run_search` behind a small protocol, so OSINT and the story share it (design D4); verify the existing OSINT search tests pass unchanged
- [x] 2.3 Split `run_research` into `research_async` plus a thin `asyncio.run` wrapper, and add a non-claiming `is_running(ticker, months)` check next to `acquire_run` (design D1); verify the OSINT CLI and API tests pass unchanged, and a new test awaits `research_async` inside a running event loop in fake mode
- [x] 2.4 Update the `osint-research` notes in `server/README.md` to say that kept findings store their excerpt; verify the README states it

## 3. Source ledger and dates

- [x] 3.1 Implement the story source ledger keyed by normalized URL, with content-derived `SRC:<n>` ids, a list of excerpts per source, origin, and the stored finding's claim, area, signal and `derived_from_filing` (design D2); verify unit tests show one id for a URL found both stored and live, stable ids across two builds, and both excerpts kept for one URL
- [x] 3.2 Implement the publish-date parser for titles and excerpts (ISO, `d.m.yyyy`, `d/m/yyyy`, Hebrew and English month names, preference for publication words, future dates ignored) (design D3); verify unit tests for each format, a contract end date skipped in favour of a `פורסם` date, and an undated excerpt
- [x] 3.3 Load the stored OSINT result into the ledger with the `as_of` filter (drop later findings, and undated ones when `as_of` is before today); verify unit tests for each filter case

## 4. Web numbers

- [x] 4.1 Implement `parse_web_number` (numeric pattern reused, English scale words, currency detection, no table-header scaling) (design D5); verify unit tests for "200 מיליון ש"ח", "NIS 1.2 billion", "$50 million" → USD, a money quote without a currency refused, and a stray "באלפי" in the excerpt not scaling the value
- [x] 4.2 Add the `WEB` fact kind to `FactRegistry` (content-derived id, low confidence, `failed_checks=["web_source"]`, `source_id`, `quote`), add `WEB` to the `TOKEN` pattern, and let `derive` take `WEB` inputs; verify `test_story_facts.py` covers a registered quote, a quote missing from the excerpt, a stored source without an excerpt refused, and a derived fact inheriting low confidence
- [x] 4.3 Add the press-source caveat to `caveat_text` and `WEB` display to `format_fact`; verify `test_story_verify_render.py` renders a `WEB` fact in dollars with the press caveat, and an existing low-confidence `FIN` fact keeps its current caveat text

## 5. Storyteller tools

- [x] 5.1 Implement `get_web_findings(area)` over the ledger's stored sources; verify a unit test returns only the requested area's findings with their source ids, dates and excerpts
- [x] 5.2 Implement the story `web_search` tool: hits without the search summary, dates parsed, `as_of` filtering, the cache keyed by (query, `as_of`, results per search, exclusions), cache hits counted and logged, and the limit stated in its description (design D4); verify unit tests with `FakeSearch` for a cache miss then hit (one provider call), a different `as_of` searching again, and a blocked result discarded
- [x] 5.3 Enforce the hard cap with `StorySearchLimitExceeded` and `failure_error_function=None`, counted on `StoryContext` across both storyteller attempts; verify a test where a fake storyteller asks for search 21 fails the run with the queries listed, saves nothing, and a test where the repair attempt sees the remaining count
- [x] 5.4 Implement `quote_web_number(source_id, text, unit)` over the ledger's excerpts; verify a unit test quoting from a live excerpt and from a stored excerpt, and refusing a number that appears only in the fake search summary
- [x] 5.5 Add `source_ids` to `StoryParagraph` and `Finding`, give the storyteller the web tools and the web index in its input, and update `story_storyteller.md` and `story_rules.md` (design D8); verify `prompt_hashes` changes and a test asserts the describe, change and explain agents have no web tools

## 6. Verification and the saved run

- [x] 6.1 Implement verification rules 7–10 and the rule 3 exception for post-report paragraphs, with `latest_report_published` on `PreparedStory` (design D7); verify `test_story_verify_render.py` has a passing and a failing case for each of: an unknown source, a source after `as_of`, an undated source with a past `as_of`, a web-only post-report paragraph, a web-only paragraph before the report, a web-only what-it-does paragraph, a finding with web sources and no report paragraph, and a filing-derived source alone
- [x] 6.2 Add `web_sources`, `osint` and `searches` to `StoryRun` with defaults, carry `source_ids` into rendered items, and make `rerender` resolve sources from the saved run (design D6); verify a test loads a run saved before this change, and a test re-renders a saved run after the stored OSINT result has been replaced

## 7. Pipeline: OSINT trigger and budget

- [x] 7.1 In `prepare_story`, load the stored OSINT result, decide whether it is missing or stale, and refuse with `ResearchInProgress` when the slot is taken (design D1); verify unit tests for fresh (10 days, no run), missing (run), stale (45 days, run) and in-progress (refused before any LLM call)
- [x] 7.2 In `_build`, run `research_async` inside the readers' `gather`, claim and release the slot, turn OSINT failures into warnings, and emit OSINT progress events; verify an end-to-end fake-mode test where the research run's areas finish while the readers run, its result is stored as the latest OSINT result, and the storyteller receives its findings, plus a test where `NoFindings` leaves a warning and the story still succeeds
- [x] 7.3 Add the search allowance and stored excerpts to the token estimate (design D9); verify a unit test that raising `story_max_searches` raises the estimate, and record Malam's estimate with the new defaults in the test or notes, confirming it stays under `STORY_MAX_TOKENS` (Malam ≈ 426K with 3,000-character excerpts; the default was raised to 1,500,000 by decision)
- [x] 7.4 Run the story pipeline end to end in fake mode twice on the same `as_of`; verify the second run makes no provider or search calls and produces the same story, and a third run with a raised `story_max_searches` misses the cache

## 8. API, CLI and web

- [x] 8.1 Map `ResearchInProgress` and `StorySearchLimitExceeded` to API errors, return the new `StoryRun` fields, and regenerate `server/openapi.json` and `web/src/api/schema.d.ts`; verify `test_api_story.py` covers the preflight refusal before streaming and a saved story with web sources, and the API-type check passes
- [x] 8.2 Print web citations (title, date, URL) and OSINT progress lines in the `story` CLI command; verify `test_cli_story.py` shows a web citation line and a research-progress line in fake mode
- [x] 8.3 Render web citation chips and the `WEB` fact provenance in `StoryPage.tsx`, and show OSINT progress and searches left during a live run (design D10); verify the web build and lint pass and the story checks in `web/e2e/ui-check.cjs` cover a web chip opening in a new tab and a press-number popover

## 9. Integration

- [x] 9.1 Run the full server test suite offline, `ruff check`, `ruff format --check`, the web build, lint and the API-type check; verify all pass locally and in CI (`server.yml`, `web.yml`)
- [ ] 9.2 Generate a live Malam story with the stored OSINT result removed or older than 30 days, after saying how much the OSINT run and searches may cost; verify the progress shows the research run, the saved story cites at least one web source that opens on the story page, and the usage log has story-search and OSINT records

## Workflow follow-up

- Archive `deploy-render-supabase-storage`, then `company-story-agents`, before archiving this change: its `company-story`, `analyzer-api` and `web-client` deltas modify requirements those changes introduce.
- Archive this change after review, and verify the archived `company-story`, `osint-research`, `analyzer-api` and `web-client` specs contain the new requirements.
