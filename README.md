# The Committee

Hebrew year-over-year analysis of Israeli listed companies' periodic reports (דוח תקופתי).
`plan.md` is the domain spec; `openspec/` holds the phased changes (Phase 1: foundation + client).

One repository, two independently built and deployed projects:

| Directory | What | Docs |
|---|---|---|
| `server/` | Python 3.11+: FinancialFilings client, report parsing, financial data, LLM gateway, CLI and FastAPI (REST + SSE) | [`server/README.md`](server/README.md) |
| `web/` | React + TypeScript SPA, Hebrew RTL: browser, report reader, financials, LLM playground | [`web/README.md`](web/README.md) |

The contract between them is `server/openapi.json`, which the web client turns into TypeScript types.

## Run everything locally (one command)

```bash
cp .env.example .env          # optional: fill in FR_API_KEY / OPENROUTER_API_KEY for live mode
docker compose up --build
```

- Client: http://localhost:8080 · API docs: http://localhost:8000/docs
- Data (cache, fetched reports, logs) persists in `./server/data`, mounted at `/data`.
- **Live mode is off by default** (`ALLOW_LIVE=false`): the stack serves cached data only and spends
  no provider credits or LLM money. Set `ALLOW_LIVE=true` in `.env` to allow live fetches and paid
  playground questions.
- On Linux, run the server as your user so it can write `./server/data`:
  `APP_UID=$(id -u) APP_GID=$(id -g) docker compose up --build`.

With no cached data yet, fetch Malam once (live, about 100 credits of the free 500/month):

```bash
cd server && uv sync && uv run stock-analyzer fetch MLTM 2024 2025
```

## Deploy each part separately

Both images take all configuration from environment variables and contain no secrets or data.

**Server** (`server/Dockerfile`, uvicorn on port 8000, non-root):

```bash
docker build -t stock-analyzer-server server/
docker run -p 8000:8000 -v analyzer-data:/data \
  -e FR_API_KEY=... -e OPENROUTER_API_KEY=... \
  -e ALLOW_LIVE=false -e CORS_ORIGINS=https://app.example.com \
  stock-analyzer-server
```

Mount a persistent volume at `/data` so restarts keep the cache, or set `DATABASE_URL` to keep the
state in Postgres instead (see "Hosted deployment" above). Keep `ALLOW_LIVE=false` on any shared
deployment until authentication exists (there is none in Phase 1).

**Web** (`web/Dockerfile`, nginx on port 80; or any static host serving `web/dist/`):

```bash
docker build -t stock-analyzer-web web/
docker run -p 8080:80 -e API_BASE_URL=https://api.example.com stock-analyzer-web
```

`API_BASE_URL` is written into `/config.js` when the container starts, so one image serves any
environment. For a plain static host, build with `VITE_API_BASE_URL=https://api.example.com npm run build`
and upload `web/dist/`.

Behind a TLS-intercepting proxy, pass its CA to either build as a secret, which is never stored in a
layer: `docker build --secret id=ca,src=/path/to/ca.crt ...`.

## Hosted deployment (Render + Supabase)

```
 laptop (live CLI) --writes--> Supabase Postgres <--reads/writes-- Render: stock-analyzer-api (Docker, free)
                                (schema stock_analyzer)                        ^ HTTPS
                                                                 Render: stock-analyzer-web (static site)
```

`render.yaml` defines both services. Render's free filesystem is wiped on every deploy and sleep, so
the API keeps its state in Postgres (`DATABASE_URL`) instead of `/data`; see
[`server/README.md`](server/README.md#state-store). The API is cached-only (`ALLOW_LIVE=false`).

**Secrets** (entered in Render, never committed): `DATABASE_URL` (Supabase *Session pooler* URI),
`FR_API_KEY`, `OPENROUTER_API_KEY` on the API.

**First-time setup**

1. *Supabase:* in the project, open *Connect* → *Session pooler*, copy the URI and the database
   password into `DATABASE_URL` in your local `.env`, then create the schema:
   `cd server && uv run --env-file ../.env stock-analyzer db init`.
2. *Render:* *New* → *Blueprint* → this repository (branch `main`). Enter the three secrets for
   `stock-analyzer-api`. Leave `CORS_ORIGINS` and `VITE_API_BASE_URL` empty for now.
3. After the first deploy, set `CORS_ORIGINS` on the API to the static site's URL and
   `VITE_API_BASE_URL` on the static site to the API's URL (both `https://…onrender.com`; Render
   may add a suffix to the names), then redeploy both. `/health` should show
   `"storage": {"backend": "postgres", "ok": true}` and `"allow_live": false`.
4. *GitHub:* set the repository variable `API_URL` (Settings → Secrets and variables → Actions →
   Variables) to the API URL, then run the *keepalive* workflow once. It runs daily so the free
   Supabase project never auto-pauses (7 idle days), and fails visibly if storage is down.

**Populate the data** from your machine (live, spends provider credits), then check the hosted
client shows it in cached mode:

```bash
cd server && uv run --env-file ../.env stock-analyzer fetch MLTM 2024 2025
```

**Pitch runbook**

1. The day before: open the client once (wakes the API and touches the database).
2. A minute before presenting: open `<API URL>/health` and wait for it to answer (a sleeping free
   instance takes ~30–60 s).
3. To demo live fetches or paid playground questions: Render → `stock-analyzer-api` →
   *Environment* → `ALLOW_LIVE=true` → *Save and deploy*. There is no authentication, so anyone with
   the URL can spend credits while it is on.
4. Right after: set `ALLOW_LIVE=false` again and confirm `/health` shows `"allow_live": false`.

**If something is wrong:** a database paused for inactivity shows as `"storage": {"ok": false}`
(restore it in the Supabase dashboard, ~3 min). To fall back, remove `DATABASE_URL` on the API: it
then uses the (ephemeral) file store. Supabase data is untouched either way.

## Configuration

Every variable, with its default, is listed in [`.env.example`](.env.example): credentials, `DATA_DIR`,
`DATABASE_URL`, `ALLOW_LIVE`, `CORS_ORIGINS`, model roles (`MODEL_MAIN`, `MODEL_CHEAP`), `PLAYGROUND_MAX_TOKENS`, parser
thresholds, `LLM_FAKE` (offline fake LLM), and `API_BASE_URL` / `VITE_API_BASE_URL` for the client.

## CI

Two path-filtered workflows: `.github/workflows/server.yml` (changes under `server/`: ruff, the offline
test suite on Python 3.11 including the state-store tests on a Postgres service, and an `openapi.json`
freshness check) and `.github/workflows/web.yml` (changes
under `web/` or to `server/openapi.json`: lint, build, and the generated-types staleness check), plus
the daily `.github/workflows/keepalive.yml` against the hosted API.
