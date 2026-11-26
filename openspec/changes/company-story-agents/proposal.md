# Proposal

## Why

The app shows a company's report text and its financial line items, but leaves the analyst to work out the company's story alone: what it does, what changed over the last few years, and whether management's narrative matches the numbers. That takes hours of reading three ~190-page Hebrew annual reports side by side. An agent pipeline can write that story in Hebrew. The project's ground rule (plan.md §0) is that no LLM output becomes a number without a code check, so the design has to make that rule hold by construction, not by a best-effort filter applied afterwards.

## What Changes

- **Company story.** For a tracked company, the system writes a Hebrew story from the last three annual reports published on or before `as_of`, in three sections:
  - what the company does
  - what changed across the three years
  - how the story fits the numbers. Each finding is labelled `consistent`, `tension` or `unexplained`.
- **Numbers only from code.** The LLM never writes a numeral in the story. It cites facts by id (`{{FIN:revenue:2025}}`, `{{CHG:revenue:2024-2025}}`, `{{RATIO:operating_margin:2025}}`), and code renders the values. New figures come only from a closed `derive` tool (percent change, ratio, share, sum, difference) over existing fact ids. Each result is registered with its inputs.
- **Agents with the OpenAI Agents SDK.** Agents are split by the question they answer:
  - a *describe* agent reads the latest business-description chapter
  - *change* agents explain business sections whose text actually changed between years
  - *explain* agents read each year's directors' report for management's explanation of the numbers
  - a *storyteller* combines their outputs with the facts, using tools

  Orchestration stays in code.
- **Changed sections chosen by code.** Business-description sections are aligned across the three reports by title. A text-similarity score marks each one unchanged, changed, new or dropped, and only changed, new and dropped sections reach an LLM. "Unchanged" is a fact established by code.
- **Core ratios and data-quality checks.** A small fixed registry of core ratios (growth, margins, free cash flow, leverage, liquidity) is computed in code from normalized values, together with the accounting-identity checks that touch their inputs. A fact with an input in a failed check has low confidence, and the story must say so. A `tension` finding cannot rest on low-confidence facts alone.
- **Verification before display.** Code verifies every story before it is saved or shown:
  - every fact token resolves
  - no stray numerals appear in the prose
  - every cited paragraph exists
  - caveat rules hold
- **Agent runs through the LLM gateway.** Agent model calls go through a gateway-backed model that applies the response cache and the usage/cost log, and a fake agent model keeps the test suite offline. SDK tracing to external services is off.
- **BREAKING (dependency):** the `openai` pin moves from `<3` to `>=3,<4`, because current `openai-agents` releases need it. The gateway's tests stop using `respx` for provider calls.
- **Delivery:**
  - Story runs are saved in the state store. Cached mode serves the latest saved run at no cost.
  - Live mode generates a new run and streams progress events over SSE. A token budget refuses runs that would be too large.
  - A `story` CLI command calls the same server functions.
  - A new web page shows the story. Each number shows its provenance on hover, and citations link to the source page.
- **Not included:**
  - quarterly or immediate reports
  - the full report-diff module (noise filters, typed handlers, materiality scoring)
  - the full ratio registry of plan.md §3.3
  - restatements
  - the analyst committee
  - share prices and valuation ratios

## Capabilities

### New Capabilities
- `company-story`: writing, verifying and rendering a company's Hebrew story from its last three annual reports. Covers report selection by `as_of`, the agent roles and their outputs, fact tokens and the `derive` tool, story verification, saved runs and the cost budget.
- `report-diff`: comparing a company's reports across fiscal years. In this change: aligning business-description sections by title and classifying each one as unchanged, changed, new or dropped by text similarity. The later full diff (plan.md §2) extends this capability.
- `financial-analysis`: deterministic analysis on top of normalized financial values. In this change: the core ratio registry, data-quality checks, and a confidence level and failed-check list for every derived fact. The later full ratio set, year comparison and management explanations (plan.md §3.3–3.6) extend it.

### Modified Capabilities
- `llm-gateway`: adds agent model calls through the gateway (cache, usage log, configured roles) and a fake agent model for offline tests.
- `analyzer-api`: adds story endpoints: the latest saved story (cached mode) and a streamed live story run with progress events.
- `web-client`: adds the story view.
- `state-store`: adds saved story runs to the state kept in the active backend. This capability is introduced by the in-flight change `deploy-render-supabase-storage`, which must be archived before this change.

## Impact

- **Server code:**
  - New packages: `stock_analyzer/story/` (agents, tools, facts registry, verify, render, pipeline), `stock_analyzer/diff/` (section alignment), `stock_analyzer/fin/ratios.py` and `fin/checks.py`, and `stock_analyzer/agents_model.py` (the gateway-backed SDK model and the fake).
  - Changed: `llm.py` (openai 3 client), `config.py` (story settings), `store/` (story runs in both backends plus `schema.sql`), `cli.py` (`story`), `api/routers/` (story router), `api/schemas.py`.
- **Prompts:** new files under `server/prompts/` for each agent role. Prompts are in English, and the output is in Hebrew.
- **Dependencies:** `openai>=3,<4` and `openai-agents` (a current release, pinned). `rapidfuzz` is already used by `structure.py`.
- **Tests:**
  - `test_llm.py` moves from `respx` to an injected client.
  - New offline tests for ratios and checks on the Malam fixture, section alignment, fact tokens and verification, the pipeline end to end with the fake agent model, and the story-run store contract.
- **Data:** Malam FY2023 and FY2024 reports must be fetched (only FY2025 is cached in full). A trimmed alignment fixture is needed for tests.
- **API contract:** new endpoints and schemas in `server/openapi.json`, and regenerated `web/src/api/schema.d.ts`.
- **Web:** a new `:ticker/story` route and page, a link from the company page, and e2e checks in `web/e2e/ui-check.cjs`.
- **Cost:** live story runs spend LLM credits. They are bounded by a configured token budget and by per-turn caching on reruns.
