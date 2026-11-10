# Proposal

## Why

`plan.md` specifies "The Committee" — a Hebrew year-over-year analyzer for Israeli listed companies' periodic reports — but orders the build backend-first and only sketches a Gradio UI with no API layer. We want to see and use real data from day one, so the project is re-sequenced into four phases with the **client and the basic data/LLM connections first**. That gives every later module (diff, ratios, committee) a place to show its output and a working pipeline to plug into.

## What Changes

Phase 1 (this change) builds the foundation and the client:

- **Repo layout:** one repository with two independently buildable and deployable projects: `server/` (Python: the plan.md §7 packages plus a FastAPI app) and `web/` (React SPA). `openspec/` and `plan.md` stay at the root.
- **Filings data connection:** a FinancialFilings REST client (company search, filings, report Markdown, financials, usage) with retries, a disk cache that never expires, and credit logging. Also the rule that picks the annual report out of each year's filings (plan.md §1.1–1.3).
- **Report parsing:** report Markdown → paragraphs with page citations → a structure tree of chapters, sections, subsections and notes (plan.md §1.4–1.5).
- **Raw financial data:** structured line items normalized to `Decimal` values with currency and availability date (a subset of plan.md §3.1). No ratios or checks yet.
- **LLM connection:** an OpenRouter gateway with JSON-schema output, a repair retry, caching, a cost log, streaming, and a `FakeLLM` for offline tests (plan.md §1.7).
- **Analyzer API:** a FastAPI service exposing the same functions as the `typer` CLI, over REST plus SSE for streaming, with cached and live modes.
- **Web client:** a Hebrew RTL single-page app with four views: company and filing browser, report reader with page-citation links, a financials table, and an LLM playground.
- **Deployment:** a container image for the server and a static build or image for the client. Both are configured only through environment variables, and a compose file runs them together locally.

### Roadmap (later phases, each its own OpenSpec change when reached)

| Phase | Goal | plan.md refs |
|---|---|---|
| 2 — Evals | Gold files (structure, risk items, must-appear-in-top-15), an eval harness with precision/recall reports, a model benchmark for Hebrew quality, faithfulness, JSON validity, cost and latency, and an eval results view in the client. | §2.0, §2.10, §8 |
| 3 — Year-over-year analysis | Report diff (align, text and table diff, noise, handlers, materiality, summaries), the retrieval index, financial analysis (checks, ratios, compare, restatements, explanations), and the change feed, with client views for each. | §1.6, §2, §3, §4, §6 |
| 4 — Committee | Bull, bear and risk analysts plus a chair, with claim verification and point-in-time data, **orchestrated with LangGraph**: a fan-out to the three analysts, verify nodes, a conditional chair ⇄ investigate edge capped at one investigation, `graph.stream()` feeding SSE, and a checkpointer for persistence and replay. LangGraph is the orchestrator only: nodes call our own `llm.py` and the deterministic `verify.py`. | §5, §6 |

## Capabilities

### New Capabilities
- `filings-client`: fetching companies, filings, report Markdown, financials and usage from the FinancialFilings REST API, with caching, retries, credit logging, and choosing the annual report.
- `report-parsing`: turning report Markdown into normalized, page-cited paragraphs and a structure tree of chapters, sections, subsections and notes.
- `financial-data`: normalizing provider financial line items into typed, point-in-time `FinValue` records.
- `llm-gateway`: structured and streaming LLM calls through OpenRouter, with schema validation, caching, cost logging and a fake for tests.
- `analyzer-api`: the HTTP API (REST + SSE) that exposes the server's functions to clients.
- `web-client`: the Hebrew RTL browser client and its views.
- `deployment`: independent build, configuration and runtime packaging of the server and the client.

### Modified Capabilities
None (greenfield project).

## Impact

- **New code:** `server/` (config, llm, ingest, fin, api, app CLI, tests), `web/` (Vite + React + TypeScript), `docker-compose.yml`, Dockerfiles, `.env.example`.
- **Dependencies:** the Python stack from plan.md §0 plus `fastapi`, `uvicorn` and `sse-starlette`. On the web side: React, Vite, Tailwind, shadcn/ui, TanStack Query, React Router, and `openapi-typescript` for the generated API types.
- **External services:** the FinancialFilings API (credit-billed; the free tier is 500 credits a month) and OpenRouter. Secrets come from env only.
- **Diverges from plan.md:** the Gradio UI (§6) becomes the React client, the Python packages move under `server/`, and the retrieval index (§1.6) moves to Phase 3.
- **Out of scope for Phase 1:** diff, ratios and data-quality checks, the feed, the committee, the eval harness, the retrieval index, authentication, and production hosting choices.
