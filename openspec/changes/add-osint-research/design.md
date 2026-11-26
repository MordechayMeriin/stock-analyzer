# Design

## Context

See proposal.md for motivation and specs/osint-research/spec.md for the required behavior.

Current state that shapes the approach:

- Every LLM call today goes through `stock_analyzer/llm.py` (`OpenRouterLLM`), which uses the `openai`
  Python client against OpenRouter, caches responses in the state store and logs usage. It is synchronous
  and built around single structured completions, not multi-step tool-using agents.
- `server/pyproject.toml` pins `openai>=1.40,<3` (locked at 2.54.0) because openai 3 moved to an httpx fork
  that respx cannot mock. The OpenAI Agents SDK requires `openai>=3` from 0.21.0 on; 0.20.0 (August 2026)
  is the last release that accepts `openai>=2.45,<3`.
- The state store's `kv_cache.namespace` and `usage_log.source` columns have database check constraints
  allowing only `fr` and `llm` (`store/schema.sql`), and the hosted Supabase schema is shared with the
  in-flight `deploy-render-supabase-storage` change.
- `openai/gpt-6.1-sol` exists on OpenRouter with tool calls, structured outputs and reasoning effort.
- OpenRouter's web search plugin (`plugins: [{id: "web", ...}]`, or the `:online` model suffix) runs one
  search per request. For OpenAI models the default engine is OpenAI's native search, which silently ignores
  `exclude_domains`. The Exa engine honors both `include_domains` and `exclude_domains` and costs $0.007 per
  search with up to 10 results. Results come back as `url_citation` annotations (url, title, content).

## Goals / Non-Goals

**Goals:**
- Multi-agent research using the OpenAI Agents SDK, running on OpenRouter with the existing key.
- Filing exclusion enforced in code, not only by the prompt or the provider.
- Bounded, visible cost per run, and a fully offline test path.
- No database schema change and no change to the existing gateway's behavior.

**Non-Goals:**
- API endpoint, web page, streaming progress or scheduled runs.
- Full-page scraping of results (the search excerpts are the evidence for now).
- Numeric scoring models or combining OSINT with the filing analysis.

## Decisions

### D1. Agents SDK 0.20.0 over OpenRouter's Chat Completions API
Pin `openai-agents==0.20.0`. Build each agent with `OpenAIChatCompletionsModel(model=settings.model_osint,
openai_client=AsyncOpenAI(base_url=settings.openrouter_base_url, api_key=...))` and call
`set_tracing_disabled(True)`, since tracing would try to upload to OpenAI's platform with no OpenAI key.
- *Alternative: upgrade to openai 3 and the latest SDK.* Rejected for now: it means reworking the respx
  mocks behind the existing LLM tests, which is unrelated to this change.
- *Alternative: a separate package with its own environment.* Rejected: it splits configuration, the store
  and the CLI for little gain.
- *Alternative: hand-rolled tool loop on the existing gateway.* Rejected: the user asked for the Agents SDK,
  and it gives agents-as-tools, structured outputs and run hooks out of the box.

### D2. Search is our own `web_search` tool, not `:online` on the agents' model
Agents run on the plain model with no plugin. Specialists get a `web_search(query, max_results?)` function
tool. The tool makes one synchronous OpenRouter call on the cheap model with
`extra_body={"plugins": [{"id": "web", "engine": "exa", "max_results": n, "exclude_domains": blocklist}]}`
and a short "list what you found" prompt, then returns the `url_citation` annotations as
`[{url, title, snippet}]`.
- *Why not `:online` on the agents' model:* it would search on every agent turn, including turns that only
  reason or write, which wastes money and gives no control over queries.
- *Why force `engine: "exa"`:* with OpenAI models the default native engine drops `exclude_domains` without
  an error, so filing sites could reach the agents.
- *Alternative: OpenRouter's `openrouter:web_search` server tool.* Deferred: unclear support when called
  through the Agents SDK's Chat Completions model.

### D3. Filing exclusion in three layers
1. `server/data/osint_blocklist.yaml` holds global entries (`maya.tase.co.il`, `mayafiles.tase.co.il`,
   `magna.isa.gov.il`, `financialreports.eu`) and optional per-ticker entries. Only the official filings
   are excluded: the investor-relations site and market-data sites stay open (user decision), and the
   prompts tell agents not to use annual or quarterly report documents found elsewhere. Wildcards and path
   prefixes follow OpenRouter's domain filter syntax.
2. The list is sent as `exclude_domains` on every search.
3. The tool filters every returned URL against the same list in code before returning results.
The `osint` package imports nothing from `ingest/`, `fin/` or the report and financials services, and only
reads the tracked-company list from the store. A unit test checks those imports.

### D4. Orchestrator with specialists as tools, then a synthesizer
```
 run_research(ticker, months)
   |
   v
 Orchestrator agent --as_tool--> 6 specialist agents (one per area)
   |                               each: web_search tool, output_type=AreaReport{findings[]}
   v
 code: verify findings (block-list, cited URL seen in this run, inside window)
   |
   v
 Synthesizer agent (output_type=Scorecard, sees only kept findings by id)
   |
   v
 code: check every risk/strength/area cites a kept finding id; empty area -> insufficient_data
```
The orchestrator chooses search angles and can call a specialist again to follow a lead. Specialists
return structured findings (`Finding{id, claim, area, signal, confidence, source_url, published_at,
derived_from_filing}`). Verification and the final checks run in code so they do not depend on the model
following instructions.
- *Alternative: handoffs.* Rejected: handoffs pass control and the conversation, but the orchestrator needs
  to collect results from all six areas.

### D5. Run state and verification
A per-run `RunState` object (passed as the SDK run context) records every URL the search tool returned,
the search count and the window. Findings are kept only if their URL is in that set, is not blocked and has
no publish date outside the window. Dropped findings are counted by reason in the result.

### D6. Reuse the `llm` cache namespace and usage source
Results are cached in the existing `llm` namespace under keys
`osint:{ticker}:{months}m:latest` (fake-mode results under `osint-fake:`), and usage records use source `llm` with purposes
`osint-agent:{name}` and `osint-search`. This avoids changing the check constraints in the shared Supabase
schema while another change is touching it.
- *Alternative: a new `osint` namespace and source.* Rejected for now; it needs a schema migration. Easy to
  move later because keys and purposes are already prefixed.

### D7. Usage logging through run hooks
A `RunHooks` subclass logs each agent model call from `on_llm_end` (model, tokens, latency, cost). Agents
run with `ModelSettings(preserve_raw_usage=True, extra_body={"usage": {"include": True}})`, so the SDK
keeps OpenRouter's `usage.cost` in `ModelResponse.raw_usage`. The search tool logs its own call, including
the cost OpenRouter reports, which covers the Exa charge. When a call reports no cost, the run's total
cost is shown as unknown.

### D8. Model role and limits in configuration
New settings: `MODEL_OSINT` (default `openai/gpt-6.1-sol`), `OSINT_MAX_SEARCHES` (default 40),
`OSINT_SEARCH_RESULTS` (default 8), `OSINT_MAX_TURNS` (per agent, default 12), `OSINT_WINDOW_MONTHS`
(default 36). `Settings.model_for("osint")` resolves the new role. Search calls use the `cheap` role.

### D9. Offline test path
With `LLM_FAKE=true`, the run uses a fake SDK `Model` that returns scripted agent outputs (tool calls, then
a final structured output) and a fake search function that returns fixture results. Search over HTTP is
also testable with respx, because the search tool uses the existing `openai` 2.x client.

### D10. CLI
`stock-analyzer osint TICKER [--months N] [--json] [--mode live|cached]`. It runs the async pipeline with
`asyncio.run`, prints the overall label, area labels, risks and strengths with their source URLs, and the
search count, dropped-finding counts and cost. The mode follows the existing `cached` / `live` context, so
`ALLOW_LIVE=false` serves only stored results.

### D11. Generic areas, Israeli market context, profile first
The six area descriptions are sector-neutral. `prompts/osint/israel_market.md` is included in every
agent's prompt: Israeli sources (business press, TASE, S&P Maalot and Midroog, local analysts, regulators),
what tends to matter for Israeli companies (controlling shareholders, concentration, unions, the shekel,
security), and a sector guide with the indicators to track for banks, insurers, real estate, technology,
telecom, retail, energy, defense, transport and healthcare. The orchestrator also gets `web_search` and
profiles the company first (industry, controller, competitors, regulator, traded bonds), then briefs each
specialist with that profile and the sector's indicators. Nothing is configured per company.
- *Alternative: per-sector prompt files chosen by a configured industry field.* Rejected: tracked
  companies have no industry field, and a model-made profile also handles conglomerates and holding
  companies.

## Risks / Trade-offs

- [Pinned SDK falls behind] → 0.20.0 is recent. Upgrading SDK and openai 3 together is a separate change
  once the test mocks are reworked.
- [Exa misses Hebrew-language sources] → specialists are told to search in Hebrew and English. If coverage
  is thin, add `include_domains` searches for Globes, Calcalist and TheMarker.
- [Model labels filing-derived news wrongly] → the label is informational and the source is always shown.
  Blocked filing sites never reach the model at all.
- [Search excerpts lack publish dates] → findings without a date are kept but marked low confidence.
- [Provider omits cost on some calls] → tokens are always logged, and the run total is shown as unknown.
- [Runaway cost] → search limit and per-agent turn limit. Every live run spends credit by design
  (user decision: real-time results); the latest stored result is shown when live calls are off.
- [Prompt injection from web pages] → page excerpts are data. Agents have no tool except search, so a
  malicious page can at most skew findings, which still need a verified citation.

## Migration Plan

Additive. Deploy with the new dependency and settings; there is no schema change. Roll back by removing
the command and package. Cached entries under `osint:` keys can be left or deleted.
