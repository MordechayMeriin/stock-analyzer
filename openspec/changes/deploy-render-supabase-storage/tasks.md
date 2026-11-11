# Tasks

## 1. Dependencies and configuration

- [x] 1.1 Add `psycopg[binary]` and `psycopg-pool` to `server/pyproject.toml` and refresh `uv.lock`; verify `uv sync --frozen` succeeds and `docker build server/` still builds
- [x] 1.2 Add `database_url: SecretStr | None` to `Settings`, read from `DATABASE_URL` (blank means unset), and include it in nothing that is logged or returned; verify `test_config.py` covers unset/blank/set and that the URL never appears in `repr(settings)`
- [x] 1.3 Add `DATABASE_URL` and `TEST_DATABASE_URL` to the env vars `tests/conftest.py` clears; verify the suite still passes with both exported in the shell

## 2. Store interface and filesystem backend (no behaviour change)

- [x] 2.1 Create `stock_analyzer/store/` with the `Store`/`KVCache` protocols (design D1) and `get_store(settings)`; verify `get_store` returns the fs backend when `database_url` is unset (unit test)
- [x] 2.2 Implement `FsStore` by moving today's code into it: diskcache namespaces `fr`/`llm`, `raw/<TICKER>/<year>.md` + `.meta.json` with exact newlines, financials JSON files, JSONL logs and their totals; verify the on-disk layout under `DATA_DIR` is unchanged (test lists the files written by a fetch)
- [x] 2.3 Route `FRClient` (cache, `is_cached`, `FetchLog`), `OpenRouterLLM`/`FakeLLM` (cache, `CallLog`), `services/filings.py` (`cached_filing_id`, `fetch`, financials snapshots, `FetchedReport.path` via `report_location`), `services/reports.py` (`_ensure_raw`) and `services/usage.py` (totals) through the store obtained from `Ctx`/settings; verify the whole existing test suite passes unchanged and `ruff check` / `ruff format --check` are clean
- [x] 2.4 Write `tests/unit/test_store_contract.py` with a parametrized `store` fixture (fs only for now) covering: get/set/contains per namespace, overwrite on refresh, byte-exact report round-trip with CRLF and Hebrew, `cached_filing_id`, log totals matching the old `read_*_totals` shape, and cached-only `NotCached` via `FRClient`; verify it passes

## 3. Postgres backend

- [x] 3.1 Write `stock_analyzer/store/schema.sql` per design D3/D4 (schema `stock_analyzer`, four tables, index, RLS enabled on every table, revokes from `anon`/`authenticated`, all `if not exists`); verify applying it twice to a local `postgres:17` succeeds and leaves inserted rows intact
- [x] 3.2 Implement `PgStore` (psycopg 3, shared `ConnectionPool` min 1/max 4, `prepare_threshold=None`, `sslmode` from URL, 5 s connect timeout for `ping`, upserts, `totals()` via SQL aggregates, schema check raising `StorageNotInitialized` naming `stock-analyzer db init`, error messages scrubbed of the URL); verify the contract suite passes against a local Postgres
- [x] 3.3 Extend the contract fixture with a `postgres` parameter enabled only when `TEST_DATABASE_URL` is set: the socket guard in `conftest.py` allows only that host:port, and each test runs in a random schema dropped afterwards; verify fs-only runs still block all network access and the pg runs pass locally
- [x] 3.4 Add contract cases for the missing-schema error and for an unreachable database (URL, user and password absent from the message); verify both pass on the pg parameter
- [x] 3.5 Map `StorageNotInitialized` and storage-unreachable errors to the existing configuration/upstream error JSON shape in `api/errors.py`; verify API tests assert the code and that the message carries no connection details
- [x] 3.6 Add the `stock-analyzer db init` CLI command, which applies `schema.sql` to `DATABASE_URL` and exits non-zero with a clear message when it is unset; verify `test_cli_structure.py` covers it and a local run against `postgres:17` creates the tables
- [ ] 3.7 Add a `postgres:17` service container to `.github/workflows/server.yml` and set `TEST_DATABASE_URL` for the test step; verify the workflow runs green on the branch with the pg contract cases reported as passed, not skipped

## 4. Health and usage

- [ ] 4.1 Add `storage: {backend, ok}` to `HealthOut` and `/health` (fs: data dir writable; pg: `ping()`), always answering 200 (design D6); verify API tests for fs ok, pg ok, and pg unreachable (`ok: false`, status 200, no URL in body)
- [ ] 4.2 Regenerate `server/openapi.json` and `web/src/api/schema.d.ts`; verify `scripts/export_openapi.py --check` and the web types staleness check pass, and `npm run build` succeeds
- [ ] 4.3 Confirm `/usage` totals come from the active store; verify an API test that logs records through the store and reads matching `fr_log`/`llm` totals

## 5. Configuration docs

- [ ] 5.1 Add `DATABASE_URL=` (empty) to `.env.example` with a comment: optional, use the Supabase session pooler URI, never commit; verify `test_config.py` (or a doc test) checks every `Settings` env var appears in `.env.example`
- [ ] 5.2 Update `server/README.md` with the storage backends, `db init`, and running the CLI against the hosted store (`uv run --env-file ../.env ...`); verify the documented commands run as written against local Postgres

## 6. Hosting definition and keep-alive

- [ ] 6.1 Add `render.yaml` per design D8 (Docker API: free, Frankfurt, `/health`, `PORT=8000`, `ALLOW_LIVE=false`, secrets and `CORS_ORIGINS` as `sync: false`; static web: `rootDir: web`, `npm ci && npm run build`, `dist`, rewrite `/* -> /index.html`, `VITE_API_BASE_URL` as `sync: false`); verify the Render blueprint plan/validation reports no errors and `grep` finds no secret values in the file
- [ ] 6.2 Add `.github/workflows/keepalive.yml` per design D9 (daily schedule off the hour + `workflow_dispatch`, skips with a notice when `vars.API_URL` is unset, curl with retries and 120 s timeout, `jq -e '.storage.ok == true'`); verify a manual dispatch with `API_URL` unset ends as skipped, not failed
- [ ] 6.3 Add a "Hosted deployment" section to the root `README.md`: architecture, required secrets, first-time setup order (design Migration Plan), populating from the CLI, the pitch runbook (warm up, set `ALLOW_LIVE=true`, set back to `false`), and rollback; verify every command and setting named exists in the repo or the Render/Supabase dashboards

## 7. Provision and deploy

- [ ] 7.1 Apply `schema.sql` to the Supabase project "Twin" (ref `uuphsgiqaswqtntdkqgp`) via `stock-analyzer db init` or the Supabase migration tool; verify the four tables exist in schema `stock_analyzer` with RLS enabled
- [ ] 7.2 Check the tables are not publicly reachable: request `https://uuphsgiqaswqtntdkqgp.supabase.co/rest/v1/kv_cache` with the project's anon key; verify it is refused (schema not exposed / permission denied)
- [ ] 7.3 Developer copies the session pooler URI and database password from the Supabase dashboard into their local `.env` as `DATABASE_URL` (never into chat or the repo); verify `stock-analyzer db init` against it reports the schema is already present
- [ ] 7.4 Create the Render services from `render.yaml` in the existing workspace (deploying from `main` after merge); developer enters `DATABASE_URL`, `FR_API_KEY`, `OPENROUTER_API_KEY`; verify both services deploy and the API's `/health` shows `storage: {backend: "postgres", ok: true}` and `allow_live: false`
- [ ] 7.5 Set `CORS_ORIGINS` on the API to the static site's real URL and `VITE_API_BASE_URL` on the static site to the API's real URL, then redeploy both; verify the hosted client loads the companies list without CORS errors in the browser console
- [ ] 7.6 Set the GitHub repo variable `API_URL` to the API URL and dispatch the keep-alive workflow; verify the run succeeds

## 8. End-to-end checks

- [ ] 8.1 From a developer machine, run `fetch MLTM 2024 2025` against the hosted `DATABASE_URL`; verify the hosted client (cached mode, `ALLOW_LIVE=false`) shows the Malam filings as cached and opens the FY2025 structure, report reader and financials
- [ ] 8.2 Trigger a manual redeploy of the API on Render; verify the same report is still served in cached mode afterwards with no provider calls (fr log shows only cache hits)
- [ ] 8.3 Open a deep link (e.g. a company page URL) directly on the hosted client; verify it renders instead of a 404
- [ ] 8.4 Set `ALLOW_LIVE=true` on the API in Render, wait for the restart, confirm a live request is accepted, then set it back to `false`; verify live requests are refused again and `/health` shows `allow_live: false`
- [ ] 8.5 With `DATABASE_URL` unset, run `docker compose up --build` locally; verify the stack behaves as before (fs backend, `/health` shows `backend: "fs"`) and the full offline test suite passes

## Workflow follow-up

- Optionally rename the Supabase project "Twin" to `stock-analyzer` in its dashboard settings.
- Follow-up idea (design D7): a least-privilege database role for the server.
- Archive the change after review with `/opsx:archive`, syncing the delta specs.
