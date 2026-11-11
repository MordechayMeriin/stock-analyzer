# Proposal

## Why

The app only runs locally today, and it needs a public URL for a pitch. Render's free web services have an ephemeral filesystem: it is wiped on every deploy, restart and idle sleep. The server keeps all of its state in files under `DATA_DIR`, so a free Render deployment would lose its cache constantly. Moving that state to a hosted Postgres (Supabase) makes the free tier usable. It also lets the public app serve data that was fetched live from a developer's machine, because both now read and write the same store.

## What Changes

- **Pluggable state store.** All server state goes through one storage interface with two backends:
  - Files under `DATA_DIR`: today's behaviour, and still the default. Offline tests and `docker compose` keep working unchanged.
  - Postgres: selected when `DATABASE_URL` is set.

  The state covered is:
  - the FinancialFilings response cache
  - the LLM response cache
  - fetched report Markdown and metadata
  - saved financials snapshots
  - the FinancialFilings and LLM usage logs
- **Postgres layout.** All tables live in a dedicated `stock_analyzer` schema that Supabase's public REST API does not expose, with row-level security on. The schema is created by an idempotent SQL file shipped with the server, applied with a CLI command.
- **Usage totals from the store.** `/usage` sums the log records in the active backend instead of re-reading whole JSONL files.
- **Health reports storage.** `/health` also reports which backend is active and whether it is reachable, without revealing the connection string.
- **Render deployment.** A `render.yaml` blueprint at the repo root declares:
  - the API as a Docker web service (free plan, Frankfurt), cached-only (`ALLOW_LIVE=false`) by default
  - the web client as a static site with an SPA rewrite

  Secrets (`DATABASE_URL`, `FR_API_KEY`, `OPENROUTER_API_KEY`) are entered in Render, never committed.
- **Keep-alive.** A scheduled GitHub Actions workflow calls `/health` daily. This keeps the Supabase free project from auto-pausing after 7 idle days, and the run fails visibly when storage is unreachable.
- **Pitch runbook.** The README documents three procedures:
  - populating the hosted store from the CLI (live, from a developer machine)
  - turning live mode on for a demo and off again (a Render env var, no code change)
  - warming up a sleeping free instance
- **Not included:**
  - authentication
  - importing existing local caches into Postgres (there is no real cache to carry over; data will be re-fetched)
  - Supabase Storage buckets
  - paid Render or Supabase plans

## Capabilities

### New Capabilities
- `state-store`: where and how the server persists its caches, fetched reports, financials snapshots and usage logs. Covers choosing the backend from configuration, identical behaviour across backends, durability across restarts and redeploys, and keeping database tables away from public database APIs.

### Modified Capabilities
- `deployment`:
  - "Persistent data directory" becomes a persistent state store: a data directory or a database.
  - Environment-only configuration gains the database URL.
  - New requirements: a hosted deployment definition in the repository, and a scheduled keep-alive check.
- `filings-client`: the permanent response cache is kept in the state store instead of necessarily "on disk".
- `llm-gateway`: the response cache is kept in the state store instead of necessarily "on disk".
- `analyzer-api`: the health endpoint also reports the storage backend and whether it is reachable.

## Impact

- **Server code:**
  - New: a `stock_analyzer/store/` package with the interface plus the fs and Postgres backends, and a schema SQL file.
  - Changed: `config.py` (`DATABASE_URL`); `ingest/fr_client.py` and `llm.py` (cache and log through the store); `services/filings.py`, `services/reports.py` and `services/usage.py`; `api/main.py` (health); `cli.py` (a `db init` command).
- **Dependencies:** `psycopg[binary]` and `psycopg-pool`. `diskcache` stays, for the fs backend.
- **Tests:** one storage contract suite that always runs against the fs backend, and against Postgres when `TEST_DATABASE_URL` is set. CI adds a Postgres service container for it.
- **Repo files:** `render.yaml`; `.github/workflows/keepalive.yml`; `.github/workflows/server.yml` (Postgres job); `.env.example`; `README.md`; `server/openapi.json` and `web/src/api/schema.d.ts` (the health response shape changes).
- **External systems:**
  - Supabase: the existing, empty project "Twin" (Paris, eu-west-3) is reused as this app's database.
  - Render: two new services in the existing workspace.
  - GitHub: a repository variable holding the API URL, for the keep-alive.
- **Compatibility:** local runs without `DATABASE_URL` behave exactly as before. No existing API field is removed. `/health` gains a field, and `fetch` results report a store location instead of a file path when Postgres is active.
