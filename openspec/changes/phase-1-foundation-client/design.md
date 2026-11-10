# Design

## Context

Greenfield repository: only `plan.md` and `openspec/` exist. `plan.md` is the authoritative domain spec for parsing rules, data models, thresholds and module behavior. This change follows it, except for the layout, UI and phasing decisions listed below. See proposal.md (Why) for the motivation.

Fixed constraints from plan.md §0:
- Python 3.11+.
- Code computes and verifies; the LLM only summarizes.
- `Decimal` for money.
- Direct REST calls to the provider, not its MCP server.
- No PDF processing.
- Responses cached forever; tests run offline.
- Secrets from env.
- All thresholds in config.

## Goals / Non-Goals

**Goals:**
- A thin vertical slice that works end to end (provider → parse → API → React view, and LLM → SSE → React) on Malam FY2024/FY2025.
- A server/client boundary clean enough to deploy, scale or split into separate repos without refactoring.
- A service layer that Phases 2–4 extend: the eval harness, diff, ratios, feed and committee all plug into the same API and client shell.

**Non-Goals:**
- Choosing a hosting provider, adding auth, or multi-tenancy.
- Retrieval or embeddings (Phase 3), and anything that judges or ranks content.
- Visual polish beyond a clean, usable RTL layout.

## Decisions

### D1. One repository, two independently deployable projects
```
/                      openspec/  plan.md  docker-compose.yml  .env.example
server/                pyproject.toml  Dockerfile
  stock_analyzer/      config.py llm.py
    ingest/            fr_client select parse_md structure normalize
    fin/               normalize
    services/          companies reports financials playground usage   ← shared by CLI + API
    api/               main.py routers/ schemas.py errors.py sse.py
    cli.py             typer: fetch, structure, fin-raw, usage
  prompts/  data/companies.yaml  tests/{fixtures,unit,api}
web/                   package.json  Dockerfile  vite.config.ts
  src/{api (generated types + client), routes, components, features/{browser,reader,financials,playground}}
```
The plan.md §7 packages live under `server/stock_analyzer/`. Later phases add `diff/`, `fin/` modules, `feed/` and `committee/` next to them.
*Alternatives:* separate repos, which bring contract drift and coordinated releases with no benefit for a single developer; or Python at the root with `web/` beside it, which mixes toolchains at the root and makes server-only builds untidy. The monorepo keeps atomic API+UI changes, and the strict directory boundary keeps deploys independent (deployment spec).

### D2. React SPA + FastAPI instead of Gradio
The UI needs RTL control, deep links, a tree reader, wide tables and, in Phase 4, a live multi-agent debate. Gradio limits layout and RTL. Streamlit's rerun model fights streaming. Stack: **Vite + React + TypeScript, Tailwind, shadcn/ui, TanStack Query, React Router**. Build output is static files.

### D3. Contract-first types from OpenAPI
FastAPI's pydantic schemas produce `openapi.json`. `web` runs `openapi-typescript` to generate `src/api/schema.d.ts`, and CI fails if the generated file is stale. Decimals are serialized as strings and formatted in the client, so no floats ever appear.
*Alternative:* hand-written TS types, which drift silently.

### D4. Service layer shared by CLI and API
`services/*` functions take plain arguments (`ticker`, `fy`, `mode`) and return pydantic models. `cli.py` and `api/routers/*` are thin adapters. This meets the plan's rule that the UI calls the same functions as the CLI, and gives Phase 2 evals one surface to test.

### D5. SSE for streaming, not WebSockets
Streaming is one-way (server → client), works over plain HTTP and proxies, and reconnects natively. `sse-starlette` on the server; `fetch` with a stream reader on the client, so we can POST the question and abort with `AbortController`. Event types: `delta`, `done` (usage, cost, paragraph ids) and `error`. Phase 4 reuses the same channel for LangGraph events.

### D6. Cache-first data access, with mode decided per request
The FR client owns a `diskcache` store under `DATA_DIR/cache`. Raw Markdown and metadata go to `DATA_DIR/raw/{ticker}/{fy}.md`, logs to `DATA_DIR/logs/`. `mode=cached` raises `NotCached` instead of calling the network; `ALLOW_LIVE=false` forces cached mode server-wide, which protects credits on any shared deployment. Parsed structures are recomputed from raw Markdown, since that's cheap and deterministic. A small memo cache keyed on file hash plus parser version avoids repeat work in the API.

### D7. Playground without retrieval
The user picks a node or a page range. The server sends the normalized paragraphs, labeled by paragraph id, plus the question to `MODEL_MAIN` with a fixed Hebrew-answer system prompt (`prompts/playground.md`). It rejects selections above `PLAYGROUND_MAX_TOKENS`. This tests the LLM path without Phase 3's embedding stack (bge-m3 is a heavy dependency).

### D8. Parser built against fixtures, tuned on real data
`parse_md` and `structure` follow plan.md §1.4–1.5 exactly. Fixtures are slices of the Malam Markdown (TOC, risk section, both page styles, the numbering forms) in `server/tests/fixtures/`. Full documents stay out of git. Thresholds (`token_set_ratio ≥ 85`, the 30% repeated-line cutoff, minimum business sections) live in `config.py`.

### D9. Deployment shape
- **Server image:** `python:3.11-slim`, installed with `uv`, runs `uvicorn stock_analyzer.api.main:app`, volume `/data`.
- **Web image:** multi-stage Node build → `nginx:alpine` serving `dist/`. `API_BASE_URL` is injected at container start into `/config.js`, which the app reads before boot, so one image works in any environment. `VITE_API_BASE_URL` is the build-time fallback for dev.
- **Compose:** `server` + `web`, with `.env` and `./server/data` mounted.
- Allowed CORS origins come from `CORS_ORIGINS`.

### D10. Phase 4 preview: LangGraph as the committee orchestrator (recorded now, built later)
```
evidence ─► ┬ bull ─┐
            ├ bear ─┼─► verify ─► rebuttal ─► verify ─► chair ─┬─► persist
            └ risk ─┘                                ▲          │ investigate (≤1)
                                                     └ verify ◄─┘
```
- The three analysts fan out in parallel and join at `verify`.
- `chair` has a conditional edge: an investigation counter in state caps it at one round.
- `graph.astream()` events map onto the D5 SSE channel.
- A checkpointer gives run persistence and `--replay`.
- Nodes call our own `llm.py` and the deterministic `verify.py`; no LangChain model wrappers, so caching, cost logging and `FakeLLM` keep working.
- This replaces plan.md §5.3's custom loop for orchestration only. Each agent's tool loop can stay our own minimal loop, used inside a node.

## Risks / Trade-offs

- [FR endpoint paths and fields differ from plan.md] → verify against `/api/schema/` before writing the client; keep the models permissive and log unknown fields.
- [Credit budget of 500 a month] → cache forever; cached-only default in compose; credit log and usage panel; fetch only Malam in Phase 1.
- [Hebrew bidi damage in Markdown, e.g. table names reversed] → normalize once in a shared module; compare with order-insensitive fuzzy matching.
- [Parser overfits Malam] → keep both page styles under test; Phase 3 adds 2–4 more companies (plan.md §9 step 11).
- [OpenAPI types going stale] → a CI check regenerates them and fails on any diff.
- [Live mode exposed on a shared deployment spends credits] → `ALLOW_LIVE=false` by default outside local dev; auth is deferred, so don't expose the server publicly until it exists.
- [Monorepo CI builds everything on every change] → path-filtered jobs for `server/**` and `web/**`.

## Migration Plan

Not applicable (greenfield). Rollback means reverting the change; cached data under `DATA_DIR` stays valid across versions because cache keys depend only on request path and parameters.

## Open Questions

- The exact financials endpoint and whether `include=revisions` is supported: confirmed during the FR client task; it affects only Phase 3 restatements.
- Hosting target for the shared deployment (Fly, Render, a VPS): doesn't change the images or the specs.
- Auth approach once the server is exposed beyond localhost: a separate future change.
