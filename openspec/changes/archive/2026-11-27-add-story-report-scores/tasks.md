# Tasks

## 1. Storage

- [x] 1.1 Add `report` to the `kv_cache` namespace check in `server/stock_analyzer/store/schema.sql` (drop and re-add the constraint, idempotently) and to the `Namespace` literal. Verify that a store unit test writes and reads a `report` key on the filesystem backend.

## 2. Report models and rater

- [x] 2.1 Add `server/stock_analyzer/report/models.py`:
  - Pydantic `CompanyReport`, `Axis`, `Score`, `Trend`, `Driver`, `ReportEvent`, `KeyMetric` and `AxisDetail` mirroring `web/src/features/report/types.ts`;
  - the rater output type (design D2).

  Verify with a unit test that validates `web/src/features/report/fixtures/mltm.full.json` against `CompanyReport`.
- [x] 2.2 Write `server/prompts/report_rater.md`. It defines the five axes in story terms, allows `null`, requires evidence ids and has factors cite `fact_id` (design D1). Add it to the prompt hashes. Verify that the prompt file loads through `agents.prompt`.
- [x] 2.3 Add the rater agent and its input builder (rendered story, findings, profile, `facts_table`) in `report/rater.py`, using the `main` role and purpose `report.rater`. Verify with a unit test using a fake model that the input contains the story text and fact ids.

## 3. Verify and assemble

- [x] 3.1 Add `report/verify.py` (design D3). It checks for unknown fact ids, values outside 1..10, missing axis/year entries, labels over their limits and unknown event types. Verify with unit tests, one per error kind.
- [x] 3.2 Add `report/assemble.py` (design D4). It computes trends, axis status, null sector medians, factor `display` values from the registry, key metrics with null for missing years, `detail_url`, and company and report info. Verify with unit tests: a 9→3 drop gives `down/-6/negative`; a null score sets `insufficient_data`; a factor display equals the fact's rendered value.

## 4. Service, API and CLI

- [x] 4.1 Add `services/report.py`. It loads the latest story run, returns the saved report (`{TICKER}:{run_id}`) in cached mode or raises `NotCached` with a "use live mode" message, and in live mode runs the rater with one retry on verify errors, assembles and saves. It also returns one axis detail. Verify with unit tests: cached miss, live build saves, repeat returns identical, and a second verify failure saves nothing.
- [x] 4.2 Add a router with `GET /api/companies/{ticker}/report` and `/report/axes/{axis_id}?year=`, returning not-found for an unknown axis or a year without a score. Register it, regenerate `server/openapi.json` and `web/src/api/schema.d.ts`. Verify with API tests and `npm run check:api`.
- [x] 4.3 Add the CLI command `stock-analyzer report <TICKER> [--live]`, calling the same service and printing the JSON. Verify with a CLI test that its output equals the service result.

## 5. Web client

- [x] 5.1 Switch `web/src/features/report/queries.ts` to the API for non-fixture tickers. Keep the MLTM and SPARSE fixtures, show a not-cached state with a live build action, and alias the types to the generated schema. (Done with the hand-written `types.ts` kept: the generated types mark optional fields nullable, which the components do not accept, so the API response is cast at the one load point.) Verify that `ReportPage` tests pass, including a new not-cached case.

## 6. El Al end to end

- [x] 6.1 Apply the schema change to Supabase and run `stock-analyzer report ELAL --live`. Verify:
  - the saved report has 5 axes × 2023-2025;
  - every evidence id resolves;
  - `GET /api/companies/ELAL/report?mode=cached` returns it;
  - the report page renders the radar for ELAL in the browser preview.

## Workflow follow-up

- Archive the change with `/opsx:archive` after review.
