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
Data (cache, fetched reports, logs) lives under `DATA_DIR` (default `server/data`).

## CLI

```bash
uv run stock-analyzer fetch MLTM 2024 2025        # live: selected annual reports + financials
uv run stock-analyzer structure MLTM 2025          # cached: structure tree + coverage summary
uv run stock-analyzer fin-raw MLTM                 # cached: financial values by statement/year
uv run stock-analyzer usage                        # provider credits + LLM spend
```

`--mode cached` (default for reading commands) never calls the provider; `fetch` is always live.

## API

```bash
uv run uvicorn stock_analyzer.api.main:app --port 8000
```

- Interactive docs: http://localhost:8000/docs (every endpoint, with schemas)
- Health: http://localhost:8000/health (liveness + which credentials are configured)
- Data routes take `?mode=cached|live`. With `ALLOW_LIVE=false` live requests get `403 live_disabled`.
- Errors are always `{"code": "...", "message": "..."}`; e.g. `404 company_not_found`, `409 not_cached`.
- `POST /api/playground` streams server-sent events (`delta`…, then `done` with cost and paragraph ids).
  It calls the LLM only in live mode, or with `LLM_FAKE=true` (offline fake, no key, no cost).

Main endpoints: `GET /api/companies`, `/api/companies/search?q=`, `/api/companies/{ticker}/filings`,
`/api/companies/{ticker}/financials`, `/api/companies/{ticker}/reports/{fy}/structure`,
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
uv run pytest -m live_data   # parser checks on full cached reports (skipped when not fetched)
uv run ruff check . && uv run ruff format --check .
```

Fixtures under `tests/fixtures/` are trimmed slices; rebuild them from the cache with
`uv run python scripts/make_fixtures.py`. Parsing quirks and their tests: `docs/parsing_notes.md`.
Provider endpoints and fields: `docs/fr_api.md`.
