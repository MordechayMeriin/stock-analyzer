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

Mount a persistent volume at `/data` so restarts keep the cache. Keep `ALLOW_LIVE=false` on any shared
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

## Configuration

Every variable, with its default, is listed in [`.env.example`](.env.example): credentials, `DATA_DIR`,
`ALLOW_LIVE`, `CORS_ORIGINS`, model roles (`MODEL_MAIN`, `MODEL_CHEAP`), `PLAYGROUND_MAX_TOKENS`, parser
thresholds, `LLM_FAKE` (offline fake LLM), and `API_BASE_URL` / `VITE_API_BASE_URL` for the client.

## CI

Two path-filtered workflows: `.github/workflows/server.yml` (changes under `server/`: ruff, the offline
test suite on Python 3.11, and an `openapi.json` freshness check) and `.github/workflows/web.yml` (changes
under `web/` or to `server/openapi.json`: lint, build, and the generated-types staleness check).
