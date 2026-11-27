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
and metadata, financials snapshots, the usage logs, and companies added at runtime — goes through one store
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
uv run stock-analyzer ratios MLTM [--as-of 2026-03-01]  # cached: ratios by group/year (* = low confidence)
uv run stock-analyzer compare MLTM 2023 2024 2025      # cached: business sections aligned across years
uv run stock-analyzer story MLTM                       # cached: the latest saved company story
uv run stock-analyzer story MLTM --live                # live: generate a new story (LLM cost, ~$1 for Malam)
uv run stock-analyzer osint ELAL [--months 36] [--json]  # live: OSINT stability scorecard
uv run stock-analyzer usage                        # provider credits + LLM spend
```

`--mode cached` (default for reading commands) never calls the provider; `fetch` is always live.
Always let `fetch` save the financials (never pass `--no-financials`): ratios are computed from them.

### Industry market research

`market-research` takes a tracked ticker and resolves its ISIC Rev. 5 class from the provider company
profile. It researches demand, competition, and regulation across Israel, Europe, and the US by default.
Use repeatable `--market` options to focus the brief. Each market shows source citations and evidence gaps.

```bash
uv run --env-file ../.env stock-analyzer market-research MLTM --mode live
uv run --env-file ../.env stock-analyzer market-research MLTM --mode live --market EUROPE --market US --json
uv run --env-file ../.env stock-analyzer market-research MLTM --market EUROPE --market US --json
```

Live mode uses the configured FinancialFilings and OpenRouter credentials and may incur provider charges.
Cached mode is the default and replays the latest result for the same ticker, market set, and month window.
Evidence from a narrower geography or a different industry classification retains its original scope.

### Peer financials

From `server/`, run the command in live mode to populate the cache, then replay the same query offline.

```bash
uv run --env-file ../.env stock-analyzer peer-financials MLTM --mode live
uv run --env-file ../.env stock-analyzer peer-financials MLTM
uv run --env-file ../.env stock-analyzer peer-financials MLTM --mode live --limit 5 --peer-country GB --peer-country DE
```

By default, the JSON contains up to five listed Israeli issuers in the target's exact ISIC sub-industry, ordered by provider
ID. Named foreign markets fill remaining places. `domestic_count` counts all eligible Israeli issuers before
the limit. Zero Israeli matches gives `no_domestic_matches`. A missing classification gives
`missing_sub_industry` and a null count. Each selected issuer's annual statements carry its own reporting
currency. Live mode can spend credits on the directory and one financial request per uncached selected issuer.
See the [offline peer evaluator](docs/peer_evaluation.md) for reviewed examples.

### Ratios

`ratios` (and `GET /api/companies/{ticker}/ratios`) standardizes the cached financials into a canonical
sheet chosen by the provider's statement template (`industrial`, `bank`, `insurer`), runs
accounting-identity checks on it, and computes the template's ratios for the newest five consecutive
fiscal years (`fin/canonical.py`, `fin/checks.py`, `fin/ratios.py`). Each value is exact, or missing with a
reason; a value is low confidence (`*`) when an input failed a check or was derived from other fields.
Nothing is fetched or stored: ratios are recomputed from the cached financials on every call.

### OSINT research

`osint` judges how stable a tracked company is from open sources only: news, market and bond data, credit
ratings, analyst forecasts, operations, court cases, upcoming regulation, labor and government, competition
and geopolitics. It never uses the official
filings: the filing systems (Maya, Magna) and the filings provider are on the block-list in
`data/osint_blocklist.yaml`, which is sent with every search and checked again on every result, and the
code never reads stored reports or financials. Everything else is open, including the company's
investor-relations site.

It works for any tracked company with nothing configured per company, and it is specialised in the
Israeli market: every agent gets `prompts/osint/israel_market.md` (Israeli press, TASE data, S&P Maalot
and Midroog, local analysts and regulators, controlling shareholders, the shekel, security risk, and a
guide to the indicators that matter in each sector). An orchestrating agent (OpenAI Agents SDK,
`MODEL_OSINT` on OpenRouter) first profiles the company (industry, controller, competitors, regulator),
then sends eight specialist agents to search the web with that profile (news, market, credit,
operations, legal proceedings, upcoming regulation, labor and government, competition and macro); each
search is one OpenRouter call on `MODEL_CHEAP` with the web plugin on the Exa engine.

Every finding then goes through checks:
- it must cite a URL that a search in the same run returned and be published inside the window, which by
  default covers the present and the past three years (`--months`);
- a cheap verifier model (`MODEL_CHEAP`) checks the claim against that source's excerpt: unsupported
  claims are dropped, partly supported or unverifiable ones are kept at low confidence, and each finding
  shows its verdict;
- findings about the same event (often from different articles or areas) are merged into one, which lists
  the other sources, so each event counts once.

The output centres on what matters for the company's industry: the company profile, a key-drivers section
(each driver of stability in that industry with its status and findings), and a label per area and overall
(stable / watch / fragile, or insufficient data for an area without findings), each with its importance for
the industry and its trend (improving / stable / deteriorating / unclear). It also gives up to three risks
and strengths and a Hebrew summary, every claim tied to its numbered sources.

```bash
uv run --env-file ../.env stock-analyzer osint ELAL              # text scorecard with sources
uv run --env-file ../.env stock-analyzer osint ELAL --json       # full result
LLM_FAKE=true uv run --env-file ../.env stock-analyzer osint ELAL  # offline demo, scripted agents and search
```

The ticker must be tracked in the store you point at (ELAL is tracked in the hosted store; on a local file
store add it first with `companies add`).

Cost: up to `OSINT_MAX_SEARCHES` searches per run (default 52, about $0.007 each for Exa) plus the agents'
tokens and the cheap verifier and duplicate-grouping calls, about $1.2 per run in total; the run prints the searches used and the total cost OpenRouter reported. Every live run searches
the web afresh, so each run costs credit. The latest result per ticker and window is stored (in the `llm`
cache under `osint:` keys) and is printed instead when live calls are off: `--mode cached`, or
`ALLOW_LIVE=false`. Fake-mode results are stored under separate keys and never served as real ones. Usage records go to the LLM
usage log with purposes `osint-search` and `osint-agent:<agent>`.

Over HTTP: `GET /api/companies/{ticker}/osint[?months=36]` returns the latest stored result in either mode
and never calls a provider (`409 not_cached` when there is none). `POST /api/companies/{ticker}/osint?mode=live`
(optional body `{"months": 12}`) runs fresh research and streams `progress` events, then one `done` (the
result) or `error` event; it is refused before streaming with `403 live_required`, `403 live_disabled`,
`503 missing_credential` or `409 research_in_progress` (one run per ticker and window per server process).
A run that finds nothing usable ends with `osint_no_findings`. A client that disconnects does not stop the
run; its result is still stored. The web client shows this at `/{ticker}/osint` (linked from the company page).

On the hosted deployment (Render, see the root README) OSINT runs in the same API image: the image carries
`data/osint_blocklist.yaml` and `prompts/osint/`, and `render.yaml` sets `MODEL_OSINT`,
`OSINT_MAX_SEARCHES` and `OSINT_WINDOW_MONTHS`. With `ALLOW_LIVE=false` it serves the stored results from
the shared Supabase store; a live run needs `ALLOW_LIVE=true` and `OPENROUTER_API_KEY`.

### Tracked companies

The tracked companies are the version-controlled list in `data/companies.yaml` plus companies
added at runtime, which are kept in the state store (`DATA_DIR/companies_added.json`, or the
`tracked_companies` table on Postgres). Added companies can be removed again; YAML ones cannot.
The web client adds them from a search result; the CLI does the same:

```bash
uv run stock-analyzer companies list                 # ticker, provider id, source (registry/added), names
uv run stock-analyzer companies add --fr-id 1234 --ticker ABC --name-he "חברה לדוגמה" [--name-en "Example Ltd."] [--isin IL0011234567]
uv run stock-analyzer companies remove ABC          # cached reports and financials are kept
```

`add` and `remove` run in live mode (refused when `ALLOW_LIVE=false`), and nothing is fetched on
add. Get the provider id from `GET /api/companies/search?q=<name>` or the client's search.

## API

```bash
uv run uvicorn stock_analyzer.api.main:app --port 8000
```

- Interactive docs: http://localhost:8000/docs (every endpoint, with schemas)
- Health: http://localhost:8000/health (liveness, which credentials are configured, and
  `storage: {backend, ok}`; always 200, `ok: false` when the database is unreachable)
- Data routes take `?mode=cached|live`. With `ALLOW_LIVE=false` live requests get `403 live_disabled`.
- Errors are always `{"code": "...", "message": "..."}`; e.g. `404 company_not_found`, `409 not_cached`,
  `409 report_not_processed` (the provider has no Markdown for the selected filing yet, or could not
  convert it; see `docs/fr_api.md`), `422 template_not_supported` (ratios requested for a statement
  template with no canonical fields, or for financials cached before the provider sent a template:
  refetch them).
- `GET /api/companies/{ticker}/filings` gives each year's `markdown_availability` (`available`,
  `unknown`, `processing`, `failed`) and each filing's raw `processing_status`. In live mode a cached
  filing list older than a day is fetched again (about 1 credit) when a year's selected report is
  still `processing` or `failed`.
- `POST /api/playground` streams server-sent events (`delta`…, then `done` with cost and paragraph ids).
  It calls the LLM only in live mode, or with `LLM_FAKE=true` (offline fake, no key, no cost).
- `GET /api/companies/{ticker}/story` returns the latest saved company story (no LLM or provider
  call; `409 not_cached` when there is none). `POST /api/companies/{ticker}/story` with
  `{"mode": "live", "as_of": "YYYY-MM-DD"}` runs a new one and streams `progress` events, then `done`
  with the saved run (or `error`). Report, mode and budget problems are plain JSON errors before the
  stream starts (`403` in cached mode, `413 story_too_large`, `422 story_reports_missing`).

Main endpoints: `GET /api/companies`, `/api/companies/search?q=`, `/api/companies/{ticker}/filings`,
`/api/companies/{ticker}/financials`, `/api/companies/{ticker}/ratios`, `/api/companies/{ticker}/reports/{fy}/structure`,
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
