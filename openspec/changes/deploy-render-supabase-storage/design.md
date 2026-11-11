# Design

## Context

See proposal.md for the motivation. Today's state, as found in the code:

| State | Where | Code |
|---|---|---|
| FinancialFilings response cache | `DATA_DIR/cache/fr` (diskcache / SQLite), key `fr:<sha256(path+params)>`, value `FRResponse.model_dump()` | `ingest/fr_client.py` (`FRClient.cache`, `request`, `is_cached`) |
| LLM response cache | `DATA_DIR/cache/llm` (diskcache), key `sha256(model+prompts+schema+params)`, value raw output string | `llm.py` (`OpenRouterLLM.cache`) |
| Report Markdown + metadata | `DATA_DIR/raw/<TICKER>/<year>.md` + `.meta.json` (`ReportMeta`) | `ingest/fr_client.py` (`raw_paths`, `save_report`, `load_report`, `read_exact`); `services/filings.py` (`cached_filing_id`, `fetch`); `services/reports.py` (`_ensure_raw`) |
| Financials snapshots | `DATA_DIR/raw/<TICKER>/financials[_revisions].json` | `services/filings.py` (`financials_path`, `fetch`); written only, never read back (the financials view reads through the FR cache) |
| Usage logs | `DATA_DIR/logs/fr.jsonl`, `llm.jsonl`, append-only | `FetchLog`, `CallLog`, `read_fr_totals`, `read_llm_totals`; `services/usage.py` |

The caches only ever use `get`, `set` and `in`. The logs only append and sum. That narrow surface is what makes a backend swap tractable.

Constraints from the hosting choices made during exploration:
- **Render free web service:** ephemeral disk, sleeps after 15 idle minutes, sets `$PORT` (default 10000), IPv4-only egress.
- **Supabase free project:** auto-pauses after 7 idle days. Its direct DB host is IPv6-only; the connection pooler (Supavisor) is reachable over IPv4.
- **Database:** the empty project "Twin" (ref `uuphsgiqaswqtntdkqgp`, eu-west-3 Paris), about 10 ms from Render Frankfurt.
- **Tests:** the offline suite blocks every AF_INET/AF_INET6 `connect` (`tests/conftest.py`).

## Goals / Non-Goals

**Goals:**
- Swap the storage location behind a small interface, with no change to service-level behaviour (see `specs/state-store`).
- Keep `docker compose up` and the offline test suite working with zero new setup.
- Make the hosted setup reproducible from files in the repo, with secrets entered only in Render and GitHub.

**Non-Goals:**
- Async database access. The server is synchronous end to end (httpx sync, sync services), so psycopg sync is used.
- Cache expiry or eviction. The cache stays permanent, as specified today.
- A dedicated least-privilege database role. Considered in D7; deferred.
- Migrating the parsed-report memo (`services/reports.py`) out of process memory. It is a per-process LRU and rebuilds itself.
- Changes to the web client beyond regenerated types.

## Decisions

### D1. One `Store` interface, two backends, selected by `DATABASE_URL`

A new package, `stock_analyzer/store/`:

```
store/
  __init__.py     get_store(settings) -> Store   (process-wide, cached per settings)
  base.py         Store protocol + KVCache protocol
  fs.py           FsStore: today's code moved here (diskcache, raw files, JSONL)
  pg.py           PgStore: psycopg + psycopg_pool
  schema.sql      idempotent DDL (D3)
```

The `Store` surface is just what callers use today:

- `cache(namespace: "fr" | "llm") -> KVCache`, with `get(key)`, `set(key, value)` and `__contains__(key)`.
- `save_report(ticker, year, meta, text)` and `load_report(ticker, year) -> (text, meta) | None`.
- `cached_filing_id(ticker, year) -> int | None`.
- `report_location(ticker, year) -> str`: the file path for fs, `postgres:reports/MLTM/2025` for pg. It fills `FetchedReport.path`.
- `save_financials(ticker, revisions, data)`.
- `log(source: "fr" | "llm", record: dict)` and `totals(source) -> dict`: the same totals shape `read_*_totals` return now.
- `ping() -> bool` and `close()`.

`Settings` gains `database_url: SecretStr | None`, read from `DATABASE_URL`. `get_store` returns a `PgStore` when it is set and an `FsStore` otherwise.

`FRClient`, `OpenRouterLLM`/`FakeLLM` and the services take the store from `Ctx` (or from `get_store(settings)` where there is no `Ctx`) instead of building paths. `ReportMeta` stays the metadata model for both backends.

*Alternatives:*
- **Swap only the diskcache objects** for a Postgres-backed dict. Rejected: reports and logs would still hit the disk.
- **A `STORAGE_BACKEND=fs|postgres` switch.** Rejected: one more variable, and setting it to `postgres` without a URL is an error state anyway.

### D2. Everything in Postgres, no Supabase Storage

Report Markdown runs to a few MB of Hebrew text per report, and is held twice (FR markdown pages in the cache, assembled text in `reports`). Postgres `text`/`jsonb` values are TOAST-compressed, and dozens of company-years fit well inside the 500 MB free quota.

*Alternative:* Supabase Storage buckets for the `.md` blobs. Rejected: a second API, second credentials and a second failure mode, for no gain at this size.

### D3. Schema `stock_analyzer`, four tables, idempotent DDL

```sql
create schema if not exists stock_analyzer;

create table if not exists stock_analyzer.kv_cache (
  namespace  text not null,             -- 'fr' | 'llm'
  key        text not null,
  value      jsonb not null,            -- FRResponse dump, or the LLM raw string as a JSON string
  updated_at timestamptz not null default now(),
  primary key (namespace, key));

create table if not exists stock_analyzer.reports (
  ticker      text not null,
  fiscal_year int  not null,
  filing_id   bigint not null,
  meta        jsonb not null,           -- ReportMeta
  text        text not null,            -- exact, no newline translation
  fetched_at  timestamptz not null,
  primary key (ticker, fiscal_year));

create table if not exists stock_analyzer.financials_snapshots (
  ticker     text not null,
  revisions  boolean not null,
  data       jsonb not null,
  fetched_at timestamptz not null default now(),
  primary key (ticker, revisions));

create table if not exists stock_analyzer.usage_log (
  id     bigint generated always as identity primary key,
  ts     timestamptz not null default now(),
  source text not null check (source in ('fr', 'llm')),
  record jsonb not null);
create index if not exists usage_log_source on stock_analyzer.usage_log (source);
```

Writes use `insert ... on conflict do update`, which keeps the existing overwrite semantics for refresh. `totals()` runs one `select count(*), sum(...) ... where source = %s` per source, using the same field names the JSONL records carry (`cache`, `credits`, `cache_hit`, `ok`, `cost`).

The DDL lives in `store/schema.sql`. A new `stock-analyzer db init` command applies it. On first use, `PgStore` checks `to_regclass('stock_analyzer.kv_cache')`; if the table is missing, it raises `StorageNotInitialized`, whose message names `stock-analyzer db init`. That error maps to the existing configuration-error JSON shape.

*Alternatives:*
- **Auto-create tables on startup.** Rejected: hides schema drift, and gives the runtime role DDL rights it doesn't need.
- **Supabase CLI migrations.** Rejected: a new toolchain for four tables.

### D4. Keep the tables private: non-exposed schema + RLS + revokes

Supabase's PostgREST exposes only the schemas listed in its API settings (`public`, `graphql_public` by default), so a dedicated `stock_analyzer` schema is not reachable with the anon key. As defence in depth, `schema.sql` also:
- runs `enable row level security` on every table, with no policies
- runs `revoke all on schema stock_analyzer from anon, authenticated`

The server connects as the database owner role, which bypasses RLS. The verification for `specs/state-store` "Database state not publicly reachable" is a request to `https://<ref>.supabase.co/rest/v1/kv_cache` with the anon key, which must fail.

### D5. psycopg 3 over the Supavisor session pooler, small pool, no prepared statements

- **Connection string:** the "Session pooler" URI from Supabase → Connect, of the form `postgresql://postgres.<ref>:<password>@aws-?-eu-west-3.pooler.supabase.com:5432/postgres`, with `sslmode=require`. It's IPv4-reachable from Render, and the long-lived server gets real sessions.
- **Pool:** `psycopg_pool.ConnectionPool(min_size=1, max_size=4, open on first use)`, shared per process. The free pooler allows a limited number of client connections, and one uvicorn worker plus occasional CLI runs need far fewer than that.
- **`prepare_threshold=None`:** keeps it working if someone pastes the transaction-pooler URI (port 6543) instead, which can't use prepared statements.
- **Timeouts:** a short connect timeout (5 s) for `ping()`, so `/health` answers promptly when the database is paused.

*Alternatives:*
- **`supabase-py` over PostgREST with the service-role key.** Rejected: it would need the schema exposed through the API, ties the code to Supabase, and is harder to test locally.
- **The direct DB host.** Rejected: IPv6-only, which Render's egress can't reach.
- **SQLAlchemy.** Rejected: unnecessary for about ten hand-written statements.

### D6. `/health` reports storage; it always answers 200

`HealthOut` gains `storage: {backend: "fs" | "postgres", ok: bool}`. For fs, `ok` checks that the data dir is writable. For postgres, it runs `select 1` with the 5 s timeout. The URL never appears, and errors are reduced to `ok: false`.

The endpoint stays 200 even when `ok` is false. Render's health check uses `/health`, and a 503 during a Supabase pause would make Render restart the service in a loop without fixing anything. The keep-alive job (D9) checks `storage.ok` itself. The OpenAPI document and the generated web types are regenerated, following the existing CI freshness checks.

### D7. Database role: the project owner (`postgres`) for now

The server uses the default `postgres.<ref>` pooler user. A dedicated role with DML-only rights on `stock_analyzer` would be better hygiene, but setting its password means handling a second secret by hand. For a single-tenant demo database the gain is small. This is recorded as a follow-up, and the schema file is written so such a role could be added later without changes to the tables.

### D8. Render: a blueprint with a Docker API and a static site

`render.yaml` at the repo root:

- **`stock-analyzer-api`**
  - `type: web`, `runtime: docker`, `dockerfilePath: ./server/Dockerfile`, `dockerContext: ./server`
  - `plan: free`, `region: frankfurt`, `healthCheckPath: /health`, `autoDeploy` on `main`
  - Env:
    - `PORT=8000`: the Dockerfile already listens on 8000, so the image is unchanged.
    - `ALLOW_LIVE=false`.
    - `DATABASE_URL`, `FR_API_KEY`, `OPENROUTER_API_KEY` and `CORS_ORIGINS`, all `sync: false`, entered in the dashboard. `CORS_ORIGINS` is listed here because the static site's final `onrender.com` host is only known after creation; Render appends a suffix when a name is taken.
  - No disk.
- **`stock-analyzer-web`**
  - `type: web`, `runtime: static`, `rootDir: web`
  - `buildCommand: npm ci && npm run build`, `staticPublishPath: dist`
  - A rewrite route `/* → /index.html` (the client uses `createBrowserRouter`, so deep links need it).
  - `VITE_API_BASE_URL`, `sync: false`, set to the API's `https://` URL. The committed `public/config.js` leaves `apiBaseUrl` empty, so the build-time value applies (`web/src/api/config.ts`).

The web Docker image and nginx stay for local and compose use; Render's static host makes them unnecessary in production.

*Alternatives:*
- **Native Python runtime with `uv`.** Rejected: duplicates the Dockerfile's build steps, and the image is already tested in compose.
- **The web client as a Docker nginx service.** Rejected: it would take a second free web-service slot and sleep. Static sites don't sleep.
- **Click-ops without a blueprint.** Rejected: not reproducible, and the spec requires a definition in the repo.

### D9. Keep-alive: a daily GitHub Actions job against `/health`

`.github/workflows/keepalive.yml`, triggered by `schedule` (once a day, off the hour) plus `workflow_dispatch`. It curls `${{ vars.API_URL }}/health` with `--retry 3 --max-time 120`, to absorb a roughly 60 s Render cold start, then uses `jq -e '.storage.ok == true'`. A failing run emails the repo owner.

One request a day wakes Render for about 15 minutes and opens a Supabase connection. That counts as activity, so the 7-day pause never triggers, while staying far inside Render's 750 free instance-hours. If `API_URL` is unset, the job skips with a notice instead of failing.

### D10. Tests: a shared contract suite, Postgres optional, CI with a service container

- `tests/unit/test_store_contract.py` runs the same cases against both backends via a parametrized `store` fixture:
  - get/set/contains per namespace
  - overwrite on refresh
  - exact text round-trip with CRLF and Hebrew
  - `cached_filing_id`
  - totals equivalence
  - the missing-schema error
- The `postgres` parameter runs only when `TEST_DATABASE_URL` is set. `conftest.py` then allows `connect` to that one host and port, and nothing else. Each test runs in a fresh, randomly named schema that is dropped afterwards, which needs a search-path override in `PgStore`, settable in tests only.
- `server.yml` adds a `postgres:17` service container and sets `TEST_DATABASE_URL`, so CI covers both backends.
- Existing tests keep using `FsStore` through `settings.data_dir`, unchanged.
- `DATABASE_URL` and `TEST_DATABASE_URL` are added to the env vars `conftest.py` clears, so a developer's `.env` can't leak into the offline suite.

### D11. CLI against the hosted store

The CLI reads the same env, so populating Supabase from a laptop is:

```bash
uv run --env-file ../.env stock-analyzer db init
uv run --env-file ../.env stock-analyzer fetch MLTM 2024 2025
```

`.env.example` gets `DATABASE_URL=` (empty by default) with a comment on using the session pooler URI.

## Risks / Trade-offs

- **The Supabase project pauses before the pitch anyway** (keep-alive disabled; GitHub suspends scheduled workflows after 60 days without repo activity). → The job fails loudly while the database is unreachable. The runbook says to open the app the day before. Restoring takes about 3 minutes from the dashboard.
- **Render free cold start, roughly 30–60 s, on the first request.** → The runbook says to hit `/health` a minute before presenting. A paid instance ($7/month) is a one-field change in `render.yaml` if needed.
- **Every cache read is now a network round trip** (Paris ↔ Frankfurt, about 10 ms), and the report reader may make several reads per page view. → Parsed reports are memoized in process (existing LRU). Report text is one row read, and cache keys are primary-key lookups.
- **Large rows.** One report's Markdown is a few MB in a single `text` value, well under Postgres's 1 GB field limit, and transferred once per process thanks to the memo.
- **Live mode on a public URL without auth during the pitch.** Anyone who finds the URL could spend FinancialFilings credits and OpenRouter money while it's on. → It's on only for the pitch window. `PLAYGROUND_MAX_TOKENS` bounds a single question, and turning it off is the documented next step.
- **The owner role in `DATABASE_URL`** means a leaked URL gives full control of the project. → It's held only in Render's secret env and the developer's `.env` (gitignored). D7 tracks a least-privilege role as a follow-up.
- **The two backends drift apart.** → One contract suite runs against both in CI.
- **The `onrender.com` names may get a random suffix,** which affects `CORS_ORIGINS` and `VITE_API_BASE_URL`. → Both are `sync: false` and set after the first creation; the tasks include a cross-origin smoke check.

## Migration Plan

1. Merge the code. With no `DATABASE_URL`, nothing changes for local, compose or CI runs.
2. Supabase: in the Twin project, get the session-pooler URI and database password from the dashboard, then run `stock-analyzer db init` against it. Optionally rename the project to `stock-analyzer`.
3. Render: create the services from `render.yaml`. Enter the secret env vars. After the first deploy, set `CORS_ORIGINS` (API) and `VITE_API_BASE_URL` (web) to the real URLs and redeploy.
4. GitHub: set the repo variable `API_URL` and run the keep-alive once manually.
5. Populate: run `fetch` for the demo companies from a laptop against `DATABASE_URL`, then verify that the hosted app serves them in cached mode.

**Rollback:**
- Unset `DATABASE_URL` and the server falls back to the fs backend, with an ephemeral cache on Render.
- Or suspend the Render services.
- Supabase data is untouched by a rollback.
