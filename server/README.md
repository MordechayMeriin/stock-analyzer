# Analyzer server

Python 3.11+ package `stock_analyzer`: the FinancialFilings client, report parsing, financial
data, the LLM gateway, a `typer` CLI and a FastAPI app. The CLI and the API call the same
`services/` functions.

## Setup

```bash
cd server
uv sync                     # creates .venv with runtime + dev dependencies
cp ../.env.example ../.env  # then fill in FR_API_KEY / OPENROUTER_API_KEY for live mode
```

All settings come from environment variables (see `../.env.example` for every variable and its
default). Load the file into your shell before running, for example `set -a; . ../.env; set +a`.
Data (cache, fetched reports, logs) lives in the state store: files under `DATA_DIR` (default
`server/data`), or Postgres when `DATABASE_URL` is set (see below).

## State store

Everything the server persists — the FinancialFilings and LLM response caches, fetched report text
and metadata, financials snapshots, and the usage logs — goes through one store
(`stock_analyzer/store/`). The backend is chosen by configuration:

| `DATABASE_URL` | Backend | Setup |
|---|---|---|
| unset (default) | files under `DATA_DIR` (`cache/`, `raw/`, `logs/`) | none |
| set | Postgres, schema `stock_analyzer` (`store/schema.sql`) | `stock-analyzer db init` once |

Both backends behave the same (one contract test suite runs against each). With Postgres, a
restart or redeploy keeps the cache, and every process using the same URL shares it: fetch live
from a laptop, serve cached from a deployed API.

```bash
# create (or re-check) the schema; idempotent, existing data is kept
uv run --env-file ../.env stock-analyzer db init
# populate the shared store from this machine (live, spends provider credits)
uv run --env-file ../.env stock-analyzer fetch MLTM 2024 2025
```

For Supabase, use the **Session pooler** URI from the project's *Connect* dialog: the direct
database host is IPv6-only, the pooler is reachable over IPv4. The tables live in their own schema,
which Supabase's REST API does not expose, with row-level security on. The URL is a secret: keep it
in `.env` (gitignored) or the host's secret settings, never in the repo.

## Agents

Agent features (the company story) use the OpenAI Agents SDK, but every model turn goes through
`stock_analyzer/agents_model.py`:

- `GatewayModel` wraps the SDK's chat-completions model on OpenRouter. It picks the model by
  role, caches each turn in the store's `llm` namespace (an identical rerun replays the whole
  agent loop at zero cost), and logs tokens, cost and latency with the agent's purpose label.
  The cost comes from OpenRouter's usage payload (`ModelSettings.preserve_raw_usage`).
- SDK tracing is turned off: nothing is sent anywhere except OpenRouter.
- `FakeAgentModel` / `FakeAgentModels` script tool calls and final outputs for offline tests,
  and are used everywhere when `LLM_FAKE=true`.
- `run_agent` enforces the turn limit and fails with an error naming the agent.

| Setting | Default | Meaning |
|---|---|---|
| `AGENT_MAX_TURNS` | `8` | Model turns (tool calls plus the final answer) per agent run |
| `AGENT_MAX_OUTPUT_TOKENS` | `16000` | Output tokens per agent turn (separate from the playground's `LLM_MAX_TOKENS`) |
| `STORY_READER_ROLE` | `cheap` | Role of the agents that read report text |
| `STORY_WRITER_ROLE` | `main` | Role of the storyteller agent |
| `STORY_MAX_TOKENS` | `300000` | Report text a story run may send; larger runs are refused before any LLM call (a Malam FY2023–FY2025 run needs ~272K, see `docs/diff_notes.md`) |
| `STORY_DESCRIBE_INTRO_TOKENS` | `12000` | Opening business sections given to the describe agent |
| `STORY_READER_BUDGET_TOKENS` | `20000` | What each agent may read with its read tools |
| `STORY_CHANGE_BATCH_TOKENS` | `40000` | Changed sections (both full versions) per change-agent call |
| `STORY_WRITER_MAX_TURNS` | `20` | The storyteller's turn limit |

The story pipeline (`stock_analyzer/story/`): `prepare_story` selects the last three annual reports
published by `as_of`, compares their business sections, builds the fact registry and checks the token
budget, all without an LLM call. `stream_story` then runs the describe, change and explain agents in
parallel, the storyteller, verification with one repair turn, and rendering, yielding progress events.
Prompts are `prompts/story_*.md`.

**Measured on a live Malam FY2023–FY2025 run** (both roles on `openai/gpt-6.2-sol`, 2026-11-27):
nine reader agents plus the storyteller, 28 model turns, ~842K input and ~46K output tokens, about
150 seconds, and **$0.81** with 5 turns served from the cache. The story passed verification on its
first attempt. A run with no cache hits costs roughly $1. The change agents' ~185K tokens of section
text dominate the cost, so a cheaper `MODEL_CHEAP` for `STORY_READER_ROLE=cheap` is the main lever.
Every agent turn is cached, so an identical rerun replays at no cost.

**Hosted database:** use Supabase's *transaction-mode* pooler (port 6543) in `DATABASE_URL`. The
session-mode pooler (port 5432) allows 15 clients across every server and CLI run, and parallel
story agents exceeded it (`EMAXCONNSESSION`); the same burst of 12 connections passes on port 6543.

## CLI

```bash
uv run stock-analyzer fetch MLTM 2024 2025        # live: selected annual reports + financials
uv run stock-analyzer structure MLTM 2025          # cached: structure tree + coverage summary
uv run stock-analyzer fin-raw MLTM                 # cached: financial values by statement/year
uv run stock-analyzer ratios MLTM                  # cached: core ratios, changes, failed data checks
uv run stock-analyzer compare MLTM 2023 2024 2025  # cached: business sections aligned across years
uv run stock-analyzer story MLTM                   # cached: the latest saved company story
uv run stock-analyzer story MLTM --live            # live: generate a new story (LLM cost, ~$1 for Malam)
uv run stock-analyzer usage                        # provider credits + LLM spend
```

`--mode cached` (default for reading commands) never calls the provider; `fetch` is always live.

## API

```bash
uv run uvicorn stock_analyzer.api.main:app --port 8000
```

- Interactive docs: http://localhost:8000/docs (every endpoint, with schemas)
- Health: http://localhost:8000/health (liveness, which credentials are configured, and
  `storage: {backend, ok}`; always 200, `ok: false` when the database is unreachable)
- Data routes take `?mode=cached|live`. With `ALLOW_LIVE=false` live requests get `403 live_disabled`.
- Errors are always `{"code": "...", "message": "..."}`; e.g. `404 company_not_found`, `409 not_cached`.
- `POST /api/playground` streams server-sent events (`delta`…, then `done` with cost and paragraph ids).
  It calls the LLM only in live mode, or with `LLM_FAKE=true` (offline fake, no key, no cost).
- `GET /api/companies/{ticker}/story` returns the latest saved company story (no LLM or provider
  call; `409 not_cached` when there is none). `POST /api/companies/{ticker}/story` with
  `{"mode": "live", "as_of": "YYYY-MM-DD"}` runs a new one and streams `progress` events, then `done`
  with the saved run (or `error`). Report, mode and budget problems are plain JSON errors before the
  stream starts (`403` in cached mode, `413 story_too_large`, `422 story_reports_missing`).

Main endpoints: `GET /api/companies`, `/api/companies/search?q=`, `/api/companies/{ticker}/filings`,
`/api/companies/{ticker}/financials`, `/api/companies/{ticker}/reports/{fy}/structure`,
`/api/companies/{ticker}/reports/{fy}/nodes/{node_id}`, `/api/companies/{ticker}/reports/{fy}/pages/{page}`,
`/api/companies/{ticker}/ratios`, `/api/companies/{ticker}/compare?years=…`,
`GET`/`POST /api/companies/{ticker}/story`, `GET /api/usage`.

### OpenAPI contract

`openapi.json` is committed and is the single source of the web client's TypeScript types.
After changing an endpoint or a response model:

```bash
uv run python scripts/export_openapi.py          # regenerate
uv run python scripts/export_openapi.py --check  # CI: fails when the file is stale
```

## Tests and lint

```bash
uv run pytest            # offline: sockets are blocked, HTTP is mocked, LLM is FakeLLM
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres uv run pytest
                         # also runs the store contract on Postgres (throwaway schemas, dropped after)
uv run pytest -m live_data   # parser checks on full cached reports (skipped when not fetched)
uv run ruff check . && uv run ruff format --check .
```

LLM provider calls are mocked differently from FinancialFilings calls. The Agents SDK
(`openai-agents`) requires `openai` 3, which sends requests through the `httpx2` fork, and
`respx` only intercepts `httpx`. So `tests/unit/test_llm.py` gives the gateway a real `OpenAI`
client wired to an `httpx2.MockTransport`, while FinancialFilings tests keep using `respx`.
On Windows, run the suite with `PYTHONUTF8=1`: without it, fixtures are read in the system
code page.

Fixtures under `tests/fixtures/` are trimmed slices; rebuild them from the cache with
`uv run python scripts/make_fixtures.py` (`--alignment` for the three-year business slices). Parsing quirks and their tests: `docs/parsing_notes.md`; the business-section comparison and its threshold: `docs/diff_notes.md`.
Provider endpoints and fields: `docs/fr_api.md`.
