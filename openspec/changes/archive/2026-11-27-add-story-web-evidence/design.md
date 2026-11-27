# Design

## Context

The story pipeline (`story/pipeline.py`) is orchestrated in code. Report readers run in parallel, then a storyteller with tools writes the story, code verifies it (rules 0-6 in `story/verify.py`), and verified runs are saved. Every agent turn goes through `GatewayModel`, which caches each turn keyed by instructions, input and tool definitions. A rerun is free only while tools return the same results.

OSINT research (`osint/agents.py`, `services/osint.py`) is a separate SDK pipeline. Its model calls skip the gateway's turn cache, and its result (`ResearchResult`, a list of `KeptFinding`s) is stored under `osint:<TICKER>:<months>m:latest` in the `llm` cache namespace. `run_search` (`osint/search.py`) applies the block-list, records returned URLs in `RunState.seen_urls`, and returns each hit's provider excerpt (`snippet`) plus a summary written by the search model. Hits carry **no publish date**: OpenRouter's `url_citation` annotation gives only a URL, title and excerpt.

The proposal explains why web evidence is being added. The requirements are in `specs/company-story`, `specs/osint-research`, `specs/analyzer-api` and `specs/web-client`.

## Goals / Non-Goals

**Goals:**
- Web evidence reaches the story only through code-checked paths: source ids that resolve, quotes found in excerpts, dates parsed by code.
- A rerun on the same `as_of` stays free and repeatable, now that one tool reads the live web.
- The OSINT pipeline keeps working on its own. The story only reads its stored result or starts a normal run.

**Non-Goals:**
- Fetching full article pages. The excerpt the search provider returns is the only source text.
- Running OSINT agents inside the story (specialists as storyteller tools).
- Changing the OSINT scorecard, its areas or its window.

## Decisions

### D1. Pipeline shape

```
prepare (no LLM)
  reports, facts, comparison                        (unchanged)
  load stored OSINT result -> fresh? (run_date >= today - STORY_OSINT_MAX_AGE_DAYS)
  research lock free?  else ResearchInProgress (preflight)
  token estimate += search allowance + stored findings index
        |
_build (async)
  gather( describe, change-N, explain-FY,  [OSINT research_async if missing or stale] )
        |                                        stored as latest when it finishes
  source ledger <- stored findings filtered by as_of
        |
  storyteller (attempt 1, repair) --tools--> get_facts, derive, quote_number, read_*   (existing)
                                          +  get_web_findings(area), web_search(query),
                                             quote_web_number(source_id, text, unit)
        |
  verify (rules 0-6 + 7-10) -> render -> StoryRun with web sources -> save
```

`run_research` wraps `run_pipeline` in `asyncio.run`, which cannot be called inside `_build`'s event loop. A new `research_async(ctx, ticker, months, ...)` holds the body. `run_research` becomes a thin `asyncio.run` wrapper, and the story awaits the async version inside its `gather`. Alternative considered: running the sync version with `asyncio.to_thread`. Rejected: it adds a second event loop per story and makes the fakes harder to inject.

Lock: `prepare_story` checks the OSINT run slot (a non-claiming check) so the API can return `ResearchInProgress` before streaming. `_build` claims the slot with `acquire_run` and releases it in `finally`. If another run claims the slot between those two points, the story fails with the same error.

An OSINT failure (`NoFindings` or any exception other than `MissingCredential`) becomes a warning, and the ledger starts with no stored findings. The storyteller keeps `web_search`.

### D2. One source ledger, content-derived ids

Stored findings and live hits go into one ledger keyed by normalized URL (`osint.models.normalize_url`). Each source gets the id `SRC:<n>`, where `n` is derived from a hash of the normalized URL, the same way `_content_id` makes `TXT` and `DER` ids. One URL gets one id whether it came from the stored run, a live search, or both. Ids stay the same on every replay, so later turns' cache keys don't change.

A ledger entry holds: url, title, excerpts (a list: each search may return a different excerpt for the same URL), `published_at`, origin (`stored` or `live`), and, for stored ones, the finding's claim, area, signal and `derived_from_filing`.

Alternative considered: ids `W1..Wn` and `S1..Sn` from counters. Rejected: the same URL would get two ids, and counters depend on call order.

### D3. Publish dates come from code

- Stored findings: `published_at` as the OSINT run kept it, which is already checked against the OSINT window by `verify_findings`.
- Live hits: a code date parser reads the title and the first part of the excerpt. It takes ISO dates, `d.m.yyyy`, `d/m/yyyy`, and Hebrew and English month names. It prefers a date next to a publication word (`פורסם`, `Published`, `Updated`), ignores dates after today, and otherwise leaves the source undated. The LLM never supplies a date.

The `as_of` filter, verification rule 8 and the post-report rule all read dates from the ledger only.

Alternative considered: the storyteller declares dates, as OSINT specialists do. Rejected: the post-report rule lets a paragraph rest on web sources alone, so its date has to be checked by code.

### D4. `web_search` for the story

The block-list, ledger recording and usage logging are factored out of `run_search` into a shared core that takes a small protocol (search count, limit, ledger, block-list) instead of `RunState`. Both OSINT and the story use it. On top of that core, the story tool adds:

- **Results without the summary.** The storyteller receives url, title, excerpt, parsed date and source id per hit, and never the search model's summary. Everything the storyteller can cite or quote is provider text. This also drops about 3,000 characters per search from the context.
- **The cache.** The key is `story-search:` + sha256 of (query, `as_of`, results per search, sorted exclusion list). Hits are stored in the `llm` namespace. A cache hit counts toward the limit and logs a cache-hit usage record, so a replay counts exactly like the original run.
- **The hard cap.** The count is kept on `StoryContext`, so it is shared by both storyteller attempts. Beyond the limit, the tool raises `StorySearchLimitExceeded`, which lists the queries run so far. The tool is built with `failure_error_function=None`: the SDK's default turns tool exceptions into text for the model, and that would make the cap soft.
- **The limit in the tool description** ("You have N searches for this story"). Tool definitions are part of `turn_cache_key`, so raising `STORY_MAX_SEARCHES` changes every storyteller cache key. That is how a run that crashed on the cap recovers: a rerun on the same `as_of` would otherwise replay the cached turns straight into the same crash.
- **Filtering.** Hits dated after `as_of`, and undated hits when `as_of` is before today, are dropped before the result is returned.

### D5. `WEB` facts

- `quote_web_number(source_id, text, unit)` checks that the whitespace-normalized `text` appears in one of that source's excerpts. A stored finding with no excerpt refuses with "this source has no excerpt".
- A new `parse_web_number` reuses the numeric pattern from `parse_quoted_number`. It adds English scale words (thousand, million, billion, bn, m) and currency detection within a short window around the quote: ₪, ש"ח, שקל, NIS, ILS, $, USD, דולר, €, EUR. It never applies table-header scaling. A money quote without a currency is refused.
- The fact id is `WEB:<n>`, content-derived from (source id, quote, unit, currency). The fact gets `confidence="low"`, `failed_checks=["web_source"]`, and new fields `source_id` and `quote`.
- The `TOKEN` pattern in `verify.py` gains `WEB`. `caveat_text` writes a press-source caveat for `WEB` facts ("מקור עיתונאי, לא מבוקר") and keeps the current text for facts that failed data checks.
- `derive` accepts `WEB` inputs. A derived fact inherits low confidence from its weakest input, as today.

### D6. Schemas and the saved run

- `StoryParagraph` and `Finding` gain `source_ids: list[str] = []`. `RenderedParagraph` carries them through.
- `StoryRun` gains `web_sources: dict[str, WebSource]` (only the cited sources, with excerpts), `osint: OsintUse` (stored run date, whether this story started a research run, its outcome), and `searches: list[str]`. The new fields have defaults, so runs saved before this change still load. `rerender` resolves sources from `web_sources`, never from the current OSINT result.
- `KeptFinding` gains `excerpt: str | None = None`, filled by `verify_findings` from the URL's search hit. The agent-facing `Finding` schema doesn't change, because SDK output types can't have defaults.

### D7. Verification rules

Rules 0-6 stay as they are, except rule 3, which allows the exception below. New rules:

| Rule | Check |
|---|---|
| 7 | every `source_ids` entry is in the ledger |
| 8 | no cited source is dated after `as_of`. When `as_of` is before today, no cited source is undated |
| 9 | a story paragraph with no `paragraph_ids` is in `what_changed`, cites at least one source, and every source it cites is dated in (latest report's publication date, `as_of`]. Rule 3 stops requiring a report paragraph for such paragraphs |
| 10 | an item's web sources are not all `derived_from_filing`, unless the item also cites a report paragraph and an independent source |

Rule 4 already forces caveats on low-confidence facts, and rule 5 already blocks a `tension` finding that rests only on low-confidence facts. `WEB` facts are low confidence, so both rules apply to them without new code. `PreparedStory` gains `latest_report_published: date`, taken from the selected filing's `release_datetime`.

### D8. Storyteller input and prompts

The storyteller input gains a short web index: the number of stored findings per area, the research run date, and a note that `get_web_findings(area)` returns them. Findings are fetched on demand, not pasted in, so a long OSINT result doesn't fill every turn. `get_web_findings` returns id, area, claim, signal, date, `derived_from_filing` and the excerpt.

`story_storyteller.md` and `story_rules.md` gain:
- when to search (unexplained moves, events after the latest report)
- how to cite (`source_ids`)
- the post-report rule
- that numbers come only from `quote_web_number`

### D9. Settings and the token estimate

New settings: `story_max_searches=20`, `story_search_results=5`, `story_osint_max_age_days=30`. `story_writer_max_turns` goes from 20 to 40, so 20 searches plus fact work fit, and `story_max_tokens` goes from 300K to 1.5M (see Risks). These are `story_*` keys, so `_config_hash_from` picks them up automatically.

The estimate adds `story_max_searches × story_search_results × (SNIPPET_CHARS + title allowance)` in tokens, plus the excerpts of the stored findings, in case the storyteller fetches them all.

### D10. Web page

`StoryPage.tsx` renders `source_ids` as web chips next to the page chips. They differ by an icon and a text label ("מקור רשת"), not by colour only. Each chip shows the title and date, or "תאריך לא ידוע", and opens the URL with `target="_blank" rel="noopener noreferrer"`. A `WEB` fact uses the existing provenance popover with a press-source variant: the value and currency, the source, the quote highlighted inside its excerpt, and the "not audited" note. Progress events gain the `osint_*` steps and the searches left.

## Risks / Trade-offs

- [The excerpt is the provider's, not the page's] → `WEB` facts are always low confidence with a visible caveat, and they can't carry a `tension` finding on their own.
- [The date parser picks a date that isn't the publish date, such as "the contract runs to 31.12.2027"] → It prefers dates next to publication words and drops future dates. A wrong date can only shift whether a source counts as post-report, and the source is still shown with its date for the analyst to judge.
- [Many live hits are undated, so stories with a past `as_of` get little live evidence] → That is accepted for point-in-time safety. Stored findings (dated by OSINT) still help.
- [A run that crashed on the cap replays into the same crash] → Raising the limit changes the cache keys (D4), and the crash error lists the queries and says this.
- [Cost: an OSINT run plus 20 searches on top of the story] → The OSINT run happens only when the stored result is missing or stale and is stored right away. A story crash doesn't repeat it, and a rerun on the same `as_of` is free.
- [The extra search allowance pushes large companies over `STORY_MAX_TOKENS`] → Measured in task 7.3: Malam needs about 272K of report text plus an 84K web allowance (356K; 154K and 426K once `SNIPPET_CHARS` rose to 3,000 in improve-osint-evidence), over the old 300K default, and lowering `story_search_results` alone could not fix it (320K at 2 results). Decision: `STORY_MAX_TOKENS` defaults to 1,500,000.
- [The storyteller paraphrases a claim that isn't in the excerpt] → Claims can't be checked like numbers. The citation always shows the source and its excerpt, so a reader can check.

## Migration Plan

1. Archive `company-story-agents`, so `company-story`, the story endpoints and the story view exist in `openspec/specs/`.
2. Deploy. Stored OSINT results without excerpts load as they are. Saved story runs without the new fields load with empty defaults and render as before.
3. Excerpts start accumulating with the next OSINT run, which a story will trigger once the stored result is 30 days old.
4. Rollback: revert the deploy. Stored results with `excerpt` still load in the old code, because pydantic ignores unknown fields on `KeptFinding`. Saved story runs with web sources would fail to load in the old schema only if it forbids extra fields, so check `StoryRun`'s config before relying on a rollback.

## Open Questions

- Exact date formats for the parser beyond the listed ones. Add formats as real excerpts show them, without changing the rules.
- Whether `story_search_results=5` is the right balance. Tune after the first real Malam runs.
