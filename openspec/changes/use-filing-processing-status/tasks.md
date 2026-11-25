# Tasks

## 1. Availability mapping and selection ranking

- [ ] 1.1 Add `markdown_availability(filing)` to `server/stock_analyzer/ingest/select.py`, returning `available`, `unknown`, `processing` or `failed` per design decision 1 (an unrecognised status is `unknown`). Verify with a parametrized test in `server/tests/unit/test_select.py` covering `COMPLETED`, `None`, `PENDING`, `QUEUED`, `PROCESSING`, `FAILED`, `SKIPPED` and an unrecognised value.
- [ ] 1.2 Change the ranking in `select_report` to `(availability_rank, file_size, id)` with `available = unknown > processing > failed` (design decision 2), and update the module docstring. Verify new tests in `test_select.py` for the spec scenarios "Processed report wins over a larger unprocessed one", "Unknown status counts as available" and "Only unprocessed candidates" (Delek FY2023: 61330467 over 61325682, both `QUEUED`). Verify the existing Malam, trustee-report and periodic-title tests pass unchanged.
- [ ] 1.3 Add a trimmed fixture with the Rami Levy and Delek FY2019–FY2026 10-K rows (id, title, fiscal year, extension, size, `processing_status`) from the cached provider lists to `server/tests/fixtures/`, and register it in `fixtures_meta.json`. Verify a test that `selected_by_year` gives RMLI 2025 → 33051170 `available`, RMLI 2024 → 61337033 `processing`, DLEKG 2024 → 61335802 `available`, and no FY2026 selection for Delek.

## 2. Error code and conditional filing-list refresh

- [ ] 2.1 Add `ReportNotProcessed` (code `report_not_processed`) to `server/stock_analyzer/errors.py` and map it to HTTP 409 in `api/errors.py`. Verify a test in `server/tests/api/test_api.py` that a raised `ReportNotProcessed` renders as `{"code": "report_not_processed", "message": ...}` with status 409.
- [ ] 2.2 Add `FRClient.cached_at(path, params) -> datetime | None` to `ingest/fr_client.py`, reading `fetched_at` from the cached entry without logging a hit, plus a `list_filings(..., refresh=...)` pass-through that refreshes every page. Verify tests in `server/tests/unit/test_fr_client.py`: `cached_at` returns the stored time or `None`, and `list_filings(refresh=True)` makes network calls and overwrites the cache using a mock transport.
- [ ] 2.3 Add `filings_for(ctx, company, needed_years=None)` to `server/stock_analyzer/services/filings.py` per design decision 3: in live mode only, refresh once when a needed year's selected filing is `processing` or `failed` and the first cached page is older than 24 hours. Verify tests in `server/tests/unit/test_services.py` using a mock transport and a backdated cache entry for all four "Filing list refresh for unprocessed reports" scenarios: provider finished, live listing, recently cached (no call), and cached mode (no call).
- [ ] 2.4 Route `list_filings`, `company_filings` and `fetch` in `services/filings.py`, and `_ensure_raw` in `services/reports.py`, through `filings_for`. Pass the requested years where known, and `None` for the listing. Verify the existing service, API and CLI fetch tests pass, and add a test that a live `fetch` of two years makes at most one list refresh.

## 3. Fetching an unprocessed report

- [ ] 3.1 In `fetch` and `_ensure_raw`, raise `ReportNotProcessed` without calling the Markdown endpoint when the selected filing is `processing` or `failed` after `filings_for`. Wrap `get_markdown` so a `ProviderNotFound` for a filing that is not `COMPLETED` becomes `ReportNotProcessed`, while a `COMPLETED` filing keeps `ProviderNotFound` (design decision 4). The message names the ticker, year, filing id and provider status. Verify tests covering the spec scenarios "Provider has not processed the report" (no Markdown request is logged and nothing is saved), "Unknown status turns out unprocessed" and "Missing Markdown for a completed filing".
- [ ] 3.2 Make the CLI `fetch` print the `report_not_processed` message and exit non-zero, like other analyzer errors. Verify with a case in `server/tests/unit/test_cli_fetch.py`.

## 4. API contract

- [ ] 4.1 Add `processing_status: str | None` to `FilingOut` and `markdown_availability: Literal["available","unknown","processing","failed"] | None` to `FiscalYearFilings` in `services/models.py`, and fill them in `list_filings`. Verify tests in `test_services.py` and `test_api.py` for the "Year waiting for the provider", "Availability mapping" and "No selection" scenarios, and that MLTM FY2025 reports `available`.
- [ ] 4.2 Regenerate `server/openapi.json` with `server/scripts/export_openapi.py`. Verify `test_openapi_lists_every_endpoint` passes and the diff only adds the two fields and the error code description.
- [ ] 4.3 Document `processing_status` and its meaning (a hint, `COMPLETED` = Markdown available, a 404 for unprocessed filings is unbilled) in `server/docs/fr_api.md` under `list_filings` and `get_markdown`, and add `report_not_processed` to the error list in `server/README.md`. Verify the documented values match the mapping in `select.py`.

## 5. Web client

- [ ] 5.1 Run `npm run gen:api` in `web/` to regenerate `src/api/schema.d.ts`. Verify `npm run check:api` and `npm run build` pass.
- [ ] 5.2 Update `YearCard` in `web/src/features/browser/CompanyPage.tsx` per design decision 5. When a year is not cached and is `processing` or `failed`, show a warning badge (`data-testid="not-processed-badge"` / `"conversion-failed-badge"`) and a one-line Hebrew explanation, and hide the read and playground buttons. Cached years and years that are `available` or `unknown` keep their current actions. Verify `npm run lint` and `npm run build` pass.
- [ ] 5.3 Extend `web/e2e/ui-check.cjs` with a routed `/api/companies/RMLI/filings` response holding one `processing` year, one `failed` year, one cached `processing` year and one `available` year. Verify the script reports PASS for the four web-client scenarios: waiting for the provider, could not convert, cached stays readable, unknown/available.

## 6. Integration check

- [ ] 6.1 Run the full offline server suite (`uv run pytest` in `server/`), and the `live_data` tests against the hosted store (`DATABASE_URL`, cached mode). Then run the API in cached mode against the hosted store and check `GET /api/companies/RMLI/filings` and `/api/companies/DLEKG/filings`. Verify that RMLI FY2024 and DLEKG FY2023 report `processing`, all cached years are still `report_cached: true` with unchanged selected ids, and no provider call is logged.

## Workflow follow-up

- Archive `generalize-report-parsing` before archiving this change. Both modify "Filing endpoints" and "Company and filing browser", and these deltas are written on its text.
- Archive this change after review, and verify the merged main specs.
