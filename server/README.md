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

## CLI

```bash
uv run stock-analyzer fetch MLTM 2024 2025        # live: selected annual reports + financials
uv run stock-analyzer structure MLTM 2025          # cached: structure tree + coverage summary
uv run stock-analyzer fin-raw MLTM                 # cached: financial values by statement/year
uv run stock-analyzer ratios MLTM [--as-of 2026-03-01]  # cached: ratios by group/year (* = low confidence)
uv run stock-analyzer osint ELAL [--months 36] [--json]  # live: OSINT stability scorecard
uv run stock-analyzer usage                        # provider credits + LLM spend
```

`--mode cached` (default for reading commands) never calls the provider; `fetch` is always live.
Always let `fetch` save the financials (never pass `--no-financials`): ratios are computed from them.

### Ratios

`ratios` (and `GET /api/companies/{ticker}/ratios`) standardizes the cached financials into a canonical
sheet chosen by the provider's statement template (`industrial`, `bank`, `insurer`), runs
accounting-identity checks on it, and computes the template's ratios for the newest five consecutive
fiscal years (`fin/canonical.py`, `fin/checks.py`, `fin/ratios.py`). Each value is exact, or missing with a
reason; a value is low confidence (`*`) when an input failed a check or was derived from other fields.
Nothing is fetched or stored: ratios are recomputed from the cached financials on every call.

### OSINT research

`osint` judges how stable a tracked company is from open sources only: news, market and bond data, credit
ratings, analyst forecasts, operations, labor, competition and geopolitics. It never uses the official
filings: the filing systems (Maya, Magna) and the filings provider are on the block-list in
`data/osint_blocklist.yaml`, which is sent with every search and checked again on every result, and the
code never reads stored reports or financials. Everything else is open, including the company's
investor-relations site.

It works for any tracked company with nothing configured per company, and it is specialised in the
Israeli market: every agent gets `prompts/osint/israel_market.md` (Israeli press, TASE data, S&P Maalot
and Midroog, local analysts and regulators, controlling shareholders, the shekel, security risk, and a
guide to the indicators that matter in each sector). An orchestrating agent (OpenAI Agents SDK,
`MODEL_OSINT` on OpenRouter) first profiles the company (industry, controller, competitors, regulator),
then sends six specialist agents to search the web with that profile; each search is one OpenRouter call on `MODEL_CHEAP` with the web plugin on the Exa engine.
A finding is kept only if it cites a URL that a search in the same run returned and was published inside
the window, which by default covers the present and the past three years (`--months`). The output is a
label per area and overall (stable / watch / fragile, or insufficient data
for an area without findings), up to three risks and strengths, and a Hebrew summary, every claim tied to
its numbered sources.

```bash
uv run --env-file ../.env stock-analyzer osint ELAL              # text scorecard with sources
uv run --env-file ../.env stock-analyzer osint ELAL --json       # full result
LLM_FAKE=true uv run --env-file ../.env stock-analyzer osint ELAL  # offline demo, scripted agents and search
```

The ticker must be tracked in the store you point at (ELAL is tracked in the hosted store; on a local file
store add it first with `companies add`).

Cost: up to `OSINT_MAX_SEARCHES` searches per run (default 40, about $0.007 each for Exa) plus the agents'
tokens; the run prints the searches used and the total cost OpenRouter reported. Every live run searches
the web afresh, so each run costs credit. The latest result per ticker and window is stored (in the `llm`
cache under `osint:` keys) and is printed instead when live calls are off: `--mode cached`, or
`ALLOW_LIVE=false`. Fake-mode results are stored under separate keys and never served as real ones. Usage records go to the LLM
usage log with purposes `osint-search` and `osint-agent:<agent>`.

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

Main endpoints: `GET /api/companies`, `/api/companies/search?q=`, `/api/companies/{ticker}/filings`,
`/api/companies/{ticker}/financials`, `/api/companies/{ticker}/ratios`, `/api/companies/{ticker}/reports/{fy}/structure`,
`/api/companies/{ticker}/reports/{fy}/nodes/{node_id}`, `/api/companies/{ticker}/reports/{fy}/pages/{page}`,
`GET /api/usage`.

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

Fixtures under `tests/fixtures/` are trimmed slices; rebuild them from the cache with
`uv run python scripts/make_fixtures.py`. Parsing quirks and their tests: `docs/parsing_notes.md`.
Provider endpoints and fields: `docs/fr_api.md`.
