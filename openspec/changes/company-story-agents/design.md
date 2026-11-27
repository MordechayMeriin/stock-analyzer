# Design

## Context

See proposal.md for the motivation. The requirements are in `specs/company-story`, `specs/report-diff`, `specs/financial-analysis` and the deltas for `llm-gateway`, `analyzer-api`, `web-client` and `state-store`. Today's state, as found in the code:

| Piece | State today | Code |
|---|---|---|
| LLM gateway | Sync `openai` 2.x client to OpenRouter. JSON-schema output, one repair retry, cache in the store, usage log with cost from `extra_body={"usage": {"include": True}}`. The client can be injected. | `llm.py` (`OpenRouterLLM`, `FakeLLM`, `get_llm`) |
| `openai` pin | `>=1.40,<3`, only because `test_llm.py` mocks OpenRouter with `respx`, and openai 3 moved to an httpx fork that respx cannot mock | `pyproject.toml`, `tests/unit/test_llm.py` |
| Report structure | Chapters, business sections and subsections with stable `node_id`, `title_norm`, paragraph and page ranges. Titles are matched with `match_key`, which ignores plene/defective spelling; numbers drift between years. | `ingest/structure.py`, `docs/parsing_notes.md` |
| Financials | `FinValue` (Decimal, `available_at`, `source_filing_id`), `as_of` filtering, grouped by year. No ratios or checks yet. | `fin/normalize.py`, `services/financials.py` |
| Live/cached | `Ctx.mode`. Paid LLM calls need live mode (`playground.resolve_llm`). Token budget pattern `playground_max_tokens` → `SelectionTooLarge`. | `services/context.py`, `services/playground.py` |
| Streaming | Sync generator of `sse_event(...)` inside `EventSourceResponse`. Errors before the stream are plain JSON; errors during it are an in-band `error` event. | `api/routers/playground.py`, `api/sse.py` |
| Store | Reports, financials snapshots, KV caches and logs, fs and pg backends with a shared contract test. No place for analysis runs. | `store/` (introduced by `deploy-render-supabase-storage`) |

Sizes measured on Malam FY2025 with the existing parser: the business-description chapter is about 153K characters (~51K tokens at the configured 3 chars/token), and the directors' report about 41K characters (~14K tokens), of which its first part (results and financial position) is about 26K characters. Only FY2025 is cached in full. FY2024 exists as a 45K-character test fixture.

The server is synchronous end to end. The Agents SDK is async.

## Goals / Non-Goals

**Goals:**
- Make "no number from the LLM" hold by the shape of the output, not by a filter applied afterwards.
- Keep every LLM call under the gateway's rules (roles, cache, usage log, offline fake), including agent turns.
- Keep orchestration deterministic and testable offline end to end in under a few seconds.
- Build `report-diff` and `financial-analysis` as first slices of the plan's modules 1 and 2, so later work extends them rather than replacing them.

**Non-Goals:**
- SDK handoffs, agents-as-tools, sessions or hosted tools. The pipeline is fixed, so code runs it.
- Paragraph-level diffs, noise filtering, typed change handlers or materiality scoring (plan.md §2.3–2.7).
- Streaming the story's tokens to the client. Only progress events are streamed.
- Several stories per company in the UI. The store keeps every run, but the API and UI show the latest.
- Embeddings or a retrieval index.

## Decisions

### D1. Pipeline: code orchestrates, agents only at the leaves

```
 select 3 reports (published <= as_of)  ->  compare business sections (report-diff)
 facts registry (financial-analysis)    ->  token budget check
        |
        +-- describe agent      (latest business chapter)          \
        +-- change agents       (changed/new/dropped sections)      }  in parallel
        +-- explain agents x3   (directors' report, part 1, each FY)/
        |
        v
 storyteller (tools: get_facts, derive, quote_number, read_paragraphs)
        |
        v
 verify -> (one repair turn) -> render -> save StoryRun
```

Each agent is an SDK `Agent` with a pydantic `output_type` and a configured role: `cheap` for describe, change and explain, `main` for the storyteller. The stages run as `asyncio.gather` over `Runner.run(...)` calls.

*Alternative:* one orchestrator agent with handoffs to sub-agents. Rejected: the order of work is known in advance, handoffs make runs harder to test and cache, and the orchestrator would add a main-model turn for nothing.

### D2. Agent outputs (internal schemas)

- `CompanyProfile` (describe): business lines, products and customers, markets, size indicators. Each item cites paragraph ids. The agent sees the section outline of the latest business chapter, the general part (before the segment sections) in full, and a `read_section(node_id)` tool for the rest, capped by a per-agent token budget the tool enforces.
- `ChangeNote[]` (change): per changed, new or dropped section and year pair: what changed in Hebrew, a kind (`activity`, `customers`, `strategy`, `risk`, `regulation`, `organization`, `other`), and cited paragraph ids from both years. Changed sections are batched into calls up to a per-call token budget, with both versions of each section side by side.
- `ManagementClaim[]` (explain, one run per year): topic (mapped to line-item codes, such as revenue → `revenue`), the claim in Hebrew, the direction management states, and cited paragraph ids.
- `Story` (storyteller): three sections of paragraphs, plus findings `{label, text_he, fact_ids, paragraph_ids}`. Each paragraph is `{text_he, paragraph_ids, caveat_fact_ids}`.

Reader agents may use `quote_number` (D5). None of them can write a number into their own free text: the no-numerals rule is checked on every agent's text fields, not only the story's.

### D3. Fact tokens and rendering

The grammar is `{{FIN:<code>:<fy>}}`, `{{CHG:<code>:<fy0>-<fy1>}}`, `{{RATIO:<code>:<fy>}}`, `{{TXT:<n>}}` and `{{DER:<n>}}`. Ids are issued by code. `TXT` and `DER` ids come back from tool calls. Verification:
1. Every token parses and resolves in the registry.
2. After tokens are removed, no digit remains in any text field except the covered fiscal years.
3. Every paragraph id exists in its year's parsed report.
4. Every low-confidence fact referenced in a paragraph or finding is listed in that item's `caveat_fact_ids`.
5. A `tension` finding has at least one high-confidence fact.
6. Every finding has at least one fact and one paragraph.

Rendering replaces each token with a segment `{type: "fact", fact_id, display}`. The API returns paragraphs as segment lists, so the web and the CLI never format numbers themselves. The display format is set in code:
- money: whole millions with a thousands separator at or above 100M (`4,138 מיליון ₪`), one decimal below that (`65.5 מיליון ₪`), and exact below 1M
- percentages: two decimals
- percentage points: two decimals with `נ"א`
- multiples: two decimals

Caveated facts get a marker, and code writes the caveat text from the failed check ids. The LLM only declares which facts need one.

*Alternative:* free text plus a verifier that matches each number to a fact with unit and rounding tolerance (plan.md §5.4). Rejected for the story: tolerance matching is fuzzy, and a hallucinated number that happens to match a fact's rounding still passes. Tokens make the check exact.

### D4. `derive`: a closed calculator

`derive(op, fact_ids)` with `op` in `pct_change`, `ratio`, `share`, `sum`, `diff`. Units must be compatible: money with money for `sum`, `diff` and `share`, and any pair for `ratio`. The result is computed in `Decimal` and registered as `DER:<n>` with op, inputs, unit and the lowest confidence of its inputs. Errors (unknown id, incompatible units, zero divisor, sign change for `pct_change`) go back to the agent as the tool's text result, so it can recover. There is no expression language and no `eval`.

### D5. `quote_number`: numbers that exist only in text

`quote_number(paragraph_id, text, unit)` checks that `text` occurs verbatim in the paragraph (after the parser's normalization), then parses it. It handles thousands separators, decimals, `%`, and the scale words `אלף`, `מיליון` and `מיליארד` next to the quoted text or in the paragraph's table header when the paragraph is a table. The result is registered as `TXT:<n>`, citing the paragraph, with high confidence. A failed match or parse is refused with a reason.

### D6. Section comparison (`report-diff`)

Business sections (level 2 and their level-3 subsections) are aligned across the three years by `match_key(title_norm)`. Exact key matches come first, then a rapidfuzz `token_set_ratio` above a configured title threshold for the rest, one-to-one and greedy by score. Numbers are ignored because they drift. Per consecutive year pair, the text similarity is rapidfuzz `ratio` on the whitespace-normalized concatenated paragraph text of the section, with numbers kept, so updated figures count as changes. The status follows `specs/report-diff`, with `diff_unchanged_threshold` (default 0.95) in `config.py`.

*Alternative:* paragraph-level alignment with a sequence diff. That is better and is plan.md §2.2, but it is not needed to decide *which sections* to read. The section-level score is the slice that can later be refined without changing the interface.

### D7. Core ratios and checks (`financial-analysis`)

- A declarative registry in `fin/ratios.py`: code, Hebrew name, formula over line-item codes, unit, and whether changes are in percent or percentage points. It is the first entries of the plan.md §3.3 registry.
- Checks in `fin/checks.py`: BS1–BS5, IS1–IS3, CF1 and CF2, as in plan.md §3.2, each with an input code list and a tolerance in `config.py`.
- Confidence propagates through inputs: a ratio is `low` if any input code appears in a failed check for that fiscal year, and a `CHG` is `low` if either side is.
- Values come from `FinValue` filtered by `as_of`. `net_income_loss` is used for the net margin; `consolidated_net_income` is used for CFO/NI.
- Leverage and liquidity use closing balances in this change. Average balances matter for returns ratios, which are not in the core set.

### D8. `GatewayModel`: agent turns under the gateway

A class implementing the SDK's `Model` interface wraps the SDK's `OpenAIChatCompletionsModel`, which points at OpenRouter through an `AsyncOpenAI` client:
- **Cache:** the key is the hash of model id, system instructions, the serialized input items, the tool schemas, the output schema and the model settings. A hit returns the stored `ModelResponse` and logs a zero-cost hit. A miss delegates, then stores and logs. Responses are stored with `TypeAdapter(ModelResponse).dump_python(mode="json", by_alias=True)`. Without aliases, fields such as `async_` (alias `async`) do not load back as the same object (`tests/unit/test_agents_sdk.py`).
- **Cost:** the SDK's `Usage` has no cost field. The wrapper sets `ModelSettings(preserve_raw_usage=True, extra_body={"usage": {"include": True}})`, so the SDK keeps OpenRouter's usage payload, including `cost`, on `ModelResponse.raw_usage`, and the wrapper logs it from there. (Found in the 2.1 spike; this replaces the earlier plan to wrap the `AsyncOpenAI` client.)
- **Roles:** the wrapper is built from a role, never from a model id.
- **Invalid output is not cached:** a final answer that fails the agent's output schema (JSON cut
  off at the token limit, as four Malam readers were at 4,096 tokens in the first live run) is
  returned but not cached, and `run_agent` gives the agent one fresh attempt. Agent turns have their
  own output cap, `agent_max_output_tokens` (16K).
- **Cache hits cost nothing:** a replayed turn reports zero usage and cost, so run totals count only
  paid turns. A store outage on cache read or write is a miss, not a failed turn.
- **Replayable tool results:** `TXT` and `DER` ids are derived from their content (the quote or the
  operation and inputs), not from a counter. Agents run in parallel, so counter ids differed between
  runs, changed later turns' inputs, and defeated the per-turn cache.
- **Tracing:** `set_tracing_disabled(True)` at import of the story package.
- **Turn limit:** `max_turns` per agent, from configuration.
- **Fake:** `FakeAgentModel` implements the same interface with a script of responses per agent purpose, such as tool calls with arguments followed by a final JSON output. The real tools run, so tests cover tool behaviour.
- **Streaming:** not implemented (`stream_response` raises). Runs use `Runner.run`.

*Alternative:* the SDK model alone, with usage taken from `RunHooks`. Rejected: no cache, no cost and no fake, which breaks three gateway requirements.

*Alternative:* pinning `openai-agents==0.20.0`, the last release on openai 2.x. Rejected during exploration: frozen on an old SDK from day one.

### D9. openai 3 migration of the gateway

The sync client in `llm.py` moves to openai 3 with no behavioural change. `test_llm.py` replaces `respx` routes for OpenRouter with an injected fake client (`OpenRouterLLM(client=...)` already exists) that returns completion-shaped objects. The other `respx` users mock our own `httpx` calls to the FinancialFilings API and stay unchanged. The offline network block in `tests/conftest.py` stays and protects both paths.

### D10. Async inside, sync outside

`story.pipeline.run_story(ctx, ticker, as_of, llm_factory) -> Iterator[StoryEvent]` is a sync generator. It starts the async pipeline with `asyncio.run` in a worker thread and yields events from a `queue.Queue`, ending with `done(run)` or `error`. The API router and the CLI consume it exactly as the playground consumes `stream`. Store calls from async code use `asyncio.to_thread`, because the store is synchronous.

### D11. Persistence and contract

- `Store` gains `save_story_run(ticker, run)`, `latest_story_run(ticker)` and `list_story_runs(ticker)`.
- **fs backend:** `DATA_DIR/stories/<TICKER>/<created_at>.json`.
- **pg backend:** table `stock_analyzer.story_runs(id bigserial, ticker text, created_at timestamptz, as_of date, payload jsonb)` with an index on `(ticker, created_at desc)`, added to `schema.sql` idempotently.
- **`StoryRun` contents:** `as_of`, fiscal years and filing ids, the facts registry, every agent output, the verification result for each attempt, the rendered sections, models, a sha256 of each prompt file and of the story-related settings, and usage and cost totals.
- Decimal values are stored as strings.

### D12. API, CLI and web

- `GET /api/companies/{ticker}/story` returns the latest run (`StoryRunOut`), or `not_cached`.
- `POST /api/companies/{ticker}/story` with body `{mode, as_of?}` streams progress over SSE: events `progress`, then `done` or `error`. Before the stream starts, the router checks live mode (cached mode → `LiveModeDisabled`-style error), report availability and the budget (`StoryTooLarge`, 413 like `SelectionTooLarge`).
- `GET /api/companies/{ticker}/ratios` and `GET /api/companies/{ticker}/compare?years=...` call the same functions as the CLI commands `ratios` and `compare`.
- The CLI adds `story TICKER [--as-of] [--live]`, `ratios TICKER` and `compare TICKER FY...`.
- **Web:**
  - A `:ticker/story` route and `StoryPage`, linked from `CompanyPage`.
  - Fact segments render `display` with a popover on hover or focus, showing provenance from the run's registry.
  - Citations use the existing `citation_url` and reader deep links.
  - Live generation reuses the playground's SSE client in `api/sse.ts`.
  - Types come from the regenerated `schema.d.ts`.

### D13. Prompts

`server/prompts/story_{describe,change,explain,storyteller}.md`, in English with Hebrew output, following `playground.md`. Shared rules:
- use only the given text and tool results
- cite paragraph ids
- never write digits: use tokens or `quote_number`
- name sections by title
- no outside knowledge

The storyteller prompt includes the token grammar and the caveat rule. Each prompt file's hash goes into the run.

## Risks / Trade-offs

- [The SDK's `Model` interface or `ModelResponse` shape differs in the pinned release from what D8 assumes] → The first task pins the version and writes a thin round-trip test (cache a response, load it, run an agent with it) before anything builds on it.
- [OpenRouter's `usage.cost` does not survive the client wrapper] → Fall back to computing cost from tokens and a per-model price table in config. The usage log already allows `cost: null`.
- [Hebrew number words bypass the no-digits rule, e.g. "גדלו בכעשרה אחוזים"] → A deny-list check: a number word next to a unit word (`אחוז`, `מיליון`, `מיליארד`, `אלף`) is rejected like a digit. Counts of things ("שלושה מגזרים") stay allowed.
- [The 0.95 similarity threshold marks rewording as change, or misses small but material edits] → A spike on Malam FY2023–FY2025 prints per-section scores before agent work starts (task group 4). The threshold is configurable. Numbers are kept in the comparison text, so figure updates always count as changes.
- [The FY2023 Markdown has a third layout the parser has not seen] → Fetching FY2023 is an early task. New parsing quirks are fixed in `parse_md`/`structure`, with regression tests per `docs/parsing_notes.md`.
- [Storyteller tool loops resend the whole context each turn, so the main model's cost dominates] → The storyteller's input is compact (agent outputs plus a core-facts table, not report text), `read_paragraphs` is capped, and turns are limited. Expected total is roughly 80K cheap-model plus 100K main-model input tokens, about $0.40 at current prices. It is measured on the first live run and recorded in the README.
- [The data checks mark many Malam facts low-confidence, so the story is full of caveats] → This is intended: the provider data really is inconsistent. Overrides (`data/financials/overrides/`) remain the way to correct values.
- [Change overlaps the in-flight `deploy-render-supabase-storage` on `store/`] → That change is archived first. This change only adds methods and a table.
- [The openai 3 bump breaks something outside `test_llm.py`] → The full test suite and `export_openapi.py` run right after the bump, before any feature work.

## Migration Plan

1. Archive `deploy-render-supabase-storage` (or at least finish its store tasks).
2. Land the dependency bump and the gateway test migration first, with all existing tests green.
3. Deploy:
   - Run `stock-analyzer db init` against the hosted database to create the `story_runs` table (idempotent).
   - New settings have defaults; no Render env change is required.
   - The hosted server stays cached-only, so it serves saved stories generated from a developer machine against the shared store.
4. Rollback: revert the change. The `story_runs` table can stay, since nothing else reads it.

## Open Questions

- Which cheap model reads Hebrew well enough for the change and explain agents. The roles are configurable, so this can be tuned after the first live runs without spec changes.
- Whether the describe agent's general-part-in-full input fits other companies' business chapters. Its per-agent budget makes overflow visible as an error, not as a silent cut.
