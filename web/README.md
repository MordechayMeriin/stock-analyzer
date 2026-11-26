# Web client

Hebrew, right-to-left single-page app for the analyzer API: company and filing browser, report
reader with page citations, financials table, and an LLM playground.

Stack: Vite + React + TypeScript, Tailwind CSS v4, shadcn/ui components (`src/components/ui`),
TanStack Query, React Router. API types are generated from the server's OpenAPI document.

## Development

Requires Node.js 20+ and a running API server (see `../server/README.md`).

```bash
cd web
npm ci
VITE_API_BASE_URL=http://localhost:8000 npm run dev    # http://localhost:5173
```

The API must allow the client's origin: the server's default `CORS_ORIGINS` already includes
`http://localhost:5173`.

## Configuration

The client looks for the API in this order (no same-origin assumption):

1. **Runtime** — `window.__APP_CONFIG__.apiBaseUrl` from `/config.js`. The file in `public/config.js`
   is a placeholder (empty value); the web container rewrites it at start-up from `API_BASE_URL`, so one
   built image works against any API.
2. **Build time** — `VITE_API_BASE_URL`, read by Vite when you run `npm run dev` or `npm run build`.
3. Same origin (relative URLs) if neither is set.

The cached/live mode control follows the server: when `/health` reports `allow_live: false` the
control is locked to cached, with an explanation. The playground only calls the paid LLM in live mode
(or when the server runs with `LLM_FAKE=true`).

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Dev server with hot reload |
| `npm run build` | Type-check and build the static bundle into `dist/` |
| `npm run lint` | Lint (oxlint) |
| `npm run gen:api` | Regenerate `src/api/schema.d.ts` from `../server/openapi.json` |
| `npm run check:api` | Fail if `schema.d.ts` is stale (used in CI) |
| `npm run preview` | Serve the built bundle locally |

After the server's API changes: in `server/`, run `uv run python scripts/export_openapi.py`, then here
`npm run gen:api`, and commit both files.

## Layout

```
src/api/        generated schema.d.ts, typed client, SSE helper, base-URL config
src/app/        cached/live mode context (driven by /health)
src/components/ shell, mode control, usage panel, structure tree, paragraphs, shared states, ui/
src/features/   browser, reader, financials, playground, story
e2e/            ui-check.cjs: browser checks against a running stack (Playwright)
```

Routes: `/`, `/:ticker`, `/:ticker/financials`, `/:ticker/story`, `/:ticker/:fy/report/:nodeId?`,
`/:ticker/:fy/playground`.

## Company story page

`/:ticker/story` shows the latest saved story (`GET /api/companies/{ticker}/story`): the covered fiscal
years and `as_of`, what the company does, what changed, and the story-versus-numbers findings with their
label in words. Numbers are rendered by the server; hovering or focusing one shows its provenance (exact
value, inputs or operation, quote, source filing, confidence and failed data checks), and low-confidence
numbers carry a mark. Each citation links to its PDF page and to the section in the report reader. In live
mode the side panel starts a new run (`POST`, server-sent `progress` events, then the saved run); in
cached mode it explains why it is disabled.

## Browser checks

`e2e/ui-check.cjs` drives a running stack with Playwright: the API on :8000 (cached-only) and :8001 (live
allowed) with cached Malam data and a saved Malam story, and the dev server on :5173.

```bash
SHOTS=/tmp/shots node e2e/ui-check.cjs                  # everything
ONLY=story WEB_URL=http://localhost:5183 API_URL=http://localhost:8010 node e2e/ui-check.cjs
```

`ONLY=story` needs only the cached API and the dev server: the live-generation check patches `/health`
and answers the story `POST` with a canned event stream, so it makes no LLM call. `WEB_URL`, `API_URL`
and `LIVE_API_URL` override the default addresses.
