# Tasks

## 1. Store: runtime-added companies

- [x] 1.1 Add `source: Literal["registry", "added"] = "registry"` to `TrackedCompany` and `list_tracked` / `add_tracked` / `remove_tracked` to the `Store` protocol (design D1); verify `ruff check` and the existing suite still pass
- [x] 1.2 Implement them in `FsStore` (`DATA_DIR/companies_added.json`, temp file + `replace`, per-path lock, duplicate ticker or provider id refused); verify new cases in `tests/unit/test_store_contract.py` cover add → list → remove → list, the duplicate refusals, and that the file survives a new `FsStore` instance
- [x] 1.3 Add `stock_analyzer.tracked_companies` to `store/schema.sql` (`if not exists`, primary key on ticker, unique `fr_company_id`, RLS on, the same revokes) and implement the three methods in `PgStore` via `_q`; verify the contract suite passes against a local Postgres with `TEST_DATABASE_URL` set, and that applying `schema.sql` twice keeps the rows
- [x] 1.4 Verify a Postgres store whose schema lacks the new table raises `StorageNotInitialized` naming `stock-analyzer db init` on `list_tracked` (test in `tests/api/test_api_store.py`, pg-only)

## 2. Merged registry and service functions

- [x] 2.1 Add `load_registry(settings, store)` with the YAML-first merge rule (design D2) and `resolve_company(ctx, ticker)` in `services/companies.py`; verify unit tests cover the merged order, the case-insensitive resolve, and that a colliding store row is skipped and logged
- [x] 2.2 Switch every `resolve_ticker(ctx.settings.companies_file, …)` call in `services/filings.py`, `services/financials.py` and `services/reports.py` (and `list_tracked` / `get_company` / `search` in `services/companies.py`) to the merged registry; verify the full offline suite passes and a test resolves an added company through `filings.list_filings` against fixtures
- [x] 2.3 Add `LiveModeRequired` (`live_required`), `CompanyAlreadyTracked` (`company_already_tracked`) and `CompanyNotRemovable` (`company_not_removable`) to `errors.py` with statuses 403/409/409 in `api/errors.py`; verify a unit test maps each code to its status
- [x] 2.4 Implement `services.companies.add(ctx, input)` and `remove(ctx, ticker)`: the live precondition (D4), input validation and upper-casing (D5), the merged-view uniqueness check, the refusal to remove YAML companies, and cached data left in place; verify unit tests cover every scenario in `specs/filings-client/spec.md` "Add a tracked company" and "Remove an added company"

## 3. API

- [x] 3.1 Add `source` to `CompanyOut`, an `AddCompanyIn` request model, `POST /api/companies` (201) and `DELETE /api/companies/{ticker}` (204) in `api/routers/companies.py`, and `DELETE` to CORS `allow_methods`; verify `tests/api/test_api.py` covers every scenario in `specs/analyzer-api/spec.md` (live add, `live_required` in cached mode, `live_disabled` on a cached-only app, 409s, 404, and the list showing `source`) plus a CORS preflight for `DELETE`
- [x] 3.2 Regenerate `server/openapi.json` with `scripts/export_openapi.py`; verify the committed file matches a fresh export and that the "Published API contract" test passes

## 4. CLI

- [x] 4.1 Add a `companies` command group (`list` with the source column, `add --fr-id --ticker --name-he [--name-en] [--isin]`, `remove TICKER`) on the same service functions, with live mode by default for add/remove; verify `tests/unit/test_cli_*.py` cases run add → list → remove on the fs backend and show a clear message when `ALLOW_LIVE=false`
- [x] 4.2 Document the command group in `server/README.md` and the hosted runbook in the root `README.md` ("add a company to the hosted app from a developer machine"); verify the documented commands run as written against a local fs backend

## 5. Web client

- [x] 5.1 Regenerate `web/src/api/schema.d.ts`, add a shared `send` helper plus `api.addCompany` / `api.removeCompany` to `web/src/api/client.ts` (D7); verify `npm run check:api`, `npm run lint` and `npm run build` pass
- [x] 5.2 In `CompaniesPage.tsx`, replace the "לא במעקב" label with an "הוסף למעקב" action that opens an inline form (ticker and Hebrew name prefilled and required, English name optional). Submit through a React Query mutation that invalidates `companies` and `search`, and show API errors inline. Verify in the running app (live mode, fs backend) that adding a searched company makes it appear in the tracked list and the hit then links to it, and that a duplicate ticker shows the server's message
- [x] 5.3 Add a "הסר ממעקב" action with confirmation on `added` company cards only, outside the card link; verify in the running app that it removes the company, and that MLTM shows no such action
- [x] 5.4 Disable both actions when `mode !== 'live'`, with the explanation varying on `liveAllowed`; verify in the running app in cached mode, and against a server started with `ALLOW_LIVE=false`, that the actions are disabled with the right text and the page has no RTL or bidi problems
- [ ] 5.5 Extend `web/e2e/ui-check.cjs` (or the existing UI check) with the cached-mode disabled state; verify it passes

## 6. Integration

- [x] 6.1 Run the full server suite (`uv run pytest`, with and without `TEST_DATABASE_URL`), `ruff check`, `ruff format --check`, and the web `lint` / `check:api` / `build`; verify all pass
- [ ] 6.2 End to end on the fs backend: add a company from the UI in live mode, fetch one of its filings live, switch to cached mode and open its filings and structure, restart the server and confirm it is still tracked, then remove it; verify each step behaves as the specs describe

## Workflow follow-up

- Archive `deploy-render-supabase-storage` before archiving this change, so the state-store spec exists first.
- On the hosted deployment: run `stock-analyzer db init` against the hosted `DATABASE_URL` before or right after the deploy (design D8), then check that `GET /api/companies` returns MLTM with `source: "registry"`.
