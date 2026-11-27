# Proposal

## Why

`add-osint-research` shipped a first OSINT endpoint and page: `GET` serves the stored result, but `POST` blocks for
the several minutes a run takes with no feedback, nothing stops two paid runs of the same research at once, and
the page starts a ~$1 run on a single click. This change makes live runs streamed, guarded and confirmed, and
fills gaps in the view (undated marks, citation links, browser checks).

## What Changes

- `GET /api/companies/{ticker}/osint?months=` is unchanged in behaviour (stored result, never a provider
  call, `not_cached` when none).
- **BREAKING** `POST /api/companies/{ticker}/osint?mode=live` now takes the window in an optional
  `{ "months": n }` body (not the query) and, instead of returning JSON after the run, runs `services.osint.run_research` in live mode and streams it as server-sent events: `progress`
  events (searches used out of the limit, the area being researched or finished, the synthesis step), then
  one `done` event carrying the full `ResearchResult`, or one `error` event. Refused before the stream
  starts in cached mode (`live_required`, 403), on a cached-only server (`live_disabled`, 403), for an
  untracked ticker (`company_not_found`, 404), and while a run for the same ticker and window is already in
  progress (`research_in_progress`, 409).
- A run with no usable findings still uses `osint_no_findings`, now as an in-stream `error` event.
- The OSINT pipeline gains an optional progress callback; the CLI behaviour is unchanged.
- The web page `/:ticker/osint` is rebuilt: window choice (12/24/36/60 months), overall label and
  rationale, the six areas with their Hebrew names, labels and assessments, top risks and strengths with
  links to their cited sources, the Hebrew summary, and numbered sources with title, link, publish date,
  signal, area and confidence. Filing-derived and undated findings are visibly marked, and finding numbers in
  the text link to their sources. The run date, window, model, search count, dropped findings and cost are shown.
- In live mode the page offers "הרץ מחקר חדש", which warns that a run searches the web afresh, takes several
  minutes and costs about $1 of OpenRouter credit, asks for confirmation, then shows streamed progress and
  replaces the shown result when done. In cached mode the action is not offered and the page says how to
  enable it.
- Regenerated `server/openapi.json` and `web/src/api/schema.d.ts`; API tests (offline, `LLM_FAKE`) and
  browser checks in `web/e2e/ui-check.cjs`.

Out of scope: listing past runs (only the latest result per ticker and window is stored) and any use of
filings or the FinancialFilings provider.

## Capabilities

### New Capabilities

None. The research behaviour itself is owned by `osint-research` (introduced by `add-osint-research`) and
does not change.

### Modified Capabilities

- `analyzer-api`: "OSINT endpoints" changes the run to a streamed, single-flight live run with
  `research_in_progress`.
- `web-client`: "OSINT stability view" changes (numbered sources, citation links, open-sources note); adds
  marked filing-derived/undated findings and the confirmed live run with progress.

## Impact

- Server: `server/stock_analyzer/api/routers/` (new `osint.py` router, registered in the app),
  `api/schemas.py` (progress/done event schemas), `api/errors.py` (new codes),
  `services/osint.py` and `osint/agents.py`/`osint/search.py` (optional progress callback),
  `server/openapi.json`, `server/tests/api/`.
- Web: `web/src/features/osint/OsintPage.tsx` (new), `web/src/main.tsx` (route),
  `web/src/features/browser/CompanyPage.tsx` (link), `web/src/api/client.ts` and `web/src/api/sse.ts`
  (OSINT call and generic SSE events), `web/src/api/schema.d.ts`, `web/e2e/ui-check.cjs`.
- Builds on `add-osint-research` (merged in PR #9) and replaces its blocking run endpoint and page.
- No database schema change; no new dependencies.
