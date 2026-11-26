# Tasks

## 1. Service: progress and errors

- [x] 1.1 Move `NoFindings` to `stock_analyzer.errors` as an `AnalyzerError` with code `osint_no_findings`, add `ResearchInProgress` (`research_in_progress`), map both in `api/errors.py` (keep 422; 409); verify the existing OSINT unit tests and the CLI no-findings test still pass
- [x] 1.2 Add `OsintProgress` and the optional `on_progress` callback to `RunState`, emit it at orchestrator start, each search, each area start/done and synthesis (callback errors swallowed), and thread an `on_progress` argument through `run_research`; verify with a unit test using the fake pipeline that progress events arrive in order and `searches_used` never exceeds the limit
- [x] 1.3 Add the per-(ticker, months) run lock helper and a unit test that a second acquire fails with `ResearchInProgress` and release frees it

## 2. API endpoints

- [x] 2.1 Add `api/routers/osint.py` with `GET /api/companies/{ticker}/osint` (cached result or `not_cached`, never a provider call) and register it; verify API tests for a seeded stored result, nothing stored, untracked ticker, `mode=live` without spend, and `months=0`
- [x] 2.2 Add `POST /api/companies/{ticker}/osint` streaming `progress`/`done`/`error` from a worker thread (pre-stream checks: months, company, `live_required`, `live_disabled`, `missing_credential`, `research_in_progress`); verify API tests under `LLM_FAKE`: progress then `done`, result stored and returned by the GET, cached mode refused, cached-only server refused, concurrent run refused, `osint_no_findings` as an `error` event with the old result kept
- [x] 2.3 Add `OsintRunIn`, `OsintProgress` and `OsintEvents` schemas, regenerate `server/openapi.json`, and verify the full server suite passes with `PYTHONUTF8=1`

## 3. Web client

- [x] 3.1 Regenerate `web/src/api/schema.d.ts` (`npm run gen:api`), add OSINT types and `api.osint(ticker, signal)` to `client.ts`, and an optional `onEvent` handler to `postSse`; verify `npm run check:api`, `npm run build` and that the playground still streams
- [x] 3.2 Build `features/osint/OsintPage.tsx` (lazy route `/:ticker/osint`): overall label, six areas with Hebrew names/labels/assessments, risks and strengths linked to numbered sources, Hebrew summary, sources with link/date/signal/area, filing-derived and undated marks, run metadata, open-sources-only note, empty and error states; verify in the browser against the stored ELAL result in cached mode
- [x] 3.3 Add the live-run action: hidden in cached mode with an explanation, cost warning with confirm/cancel, streamed progress with the old result kept, new result shown on `done`, error shown on failure; verify in the browser against a fake-mode API (`LLM_FAKE=true`, `ALLOW_LIVE=true`)
- [x] 3.4 Link the OSINT view from the company page (`data-testid="osint-link"`) and add an `osint` section to `web/e2e/ui-check.cjs` covering the ELAL view, marks, citation links and the cached-mode state; verify `ONLY=osint node e2e/ui-check.cjs` passes and `npm run lint` is clean

## 4. Integration

- [x] 4.1 Run the API (`api` launch config) and web (`web` launch config) against the Supabase store in cached mode and confirm `/ELAL/osint` shows the stored ELAL result with no OpenRouter or FinancialFilings calls in the usage log

## Workflow follow-up

- Archive `add-osint-web` after `add-osint-research` is archived, so the `osint-research` spec exists in `openspec/specs/`.
