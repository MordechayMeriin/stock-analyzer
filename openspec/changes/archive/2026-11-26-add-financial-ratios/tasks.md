# Tasks

## 1. Fixtures and template

- [x] 1.1 Refresh `server/tests/fixtures/mltm_financials.json` and add `lumi_financials.json` and `harl_financials.json`. Copy them from the state-store cache entries (read-only SQL on `stock_analyzer.kv_cache`, the parsed `value->>'body'` of the financials responses for company ids 6901, 6889 and 6832), with no provider calls. Register them in `fixtures_meta.json`. Verify each file parses, carries `template` (`industrial`, `bank`, `insurer`), and that the existing tests in `server/tests/unit/test_fin_normalize.py` and `test_services_fin.py` still pass (adjust only assertions that counted periods).
- [x] 1.2 Add `financials_template(data)` to `server/stock_analyzer/fin/normalize.py` and return the template next to the values from `services/financials.py` (design D2), keeping `normalize_financials`' signature. Add `TemplateNotSupported` (`template_not_supported`) to `errors.py`, mapped to HTTP 422 in `api/errors.py`. Verify tests for the financial-data scenarios "Bank template" and "Template missing", and an API test that the error renders with status 422.

## 2. Canonical sheet

- [x] 2.1 Create `server/stock_analyzer/fin/canonical.py` with `Field`, `Code`, `Rule`, `Cell` and `build_sheet(values, template)` (design D3, D4): ordered resolution, lazy memoized rules, cycle detection when the registry loads, and provenance including `source_filing_type`. Verify unit tests in `server/tests/unit/test_fin_canonical.py` for the scenarios "Reported value wins", "Derived when the total is missing" (Malam FY2023 common equity = 617841000), "Nothing to resolve from", "Provenance of a derived cell", "Derived sum stays exact" and "Unknown template".
- [x] 2.2 Declare the industrial, bank and insurer field sets and rules from design D3. Calibrate the `current_debt + noncurrent_debt` component fallback on Malam FY2025 so the derived total equals the reported `total_debt_bs`, and record whether leases are included in a code comment. Verify tests for "Industrial sheet" and "Bank sheet" (every year has every field of its template), and that the Malam FY2025 derived debt matches the reported value.
- [x] 2.3 Add point-in-time building: filter normalized values with the existing `as_of` before building. Verify the "Value not yet available" scenario on Malam.

## 3. Data-quality checks

- [x] 3.1 Create `server/stock_analyzer/fin/checks.py` with the `Check` registry and `run_checks(sheet)` for BS1, BS2, BS3, BS5, IS1, IS2, CF1 and CF3, with the tolerance from design D5. Verify tests in `server/tests/unit/test_fin_checks.py`: each check passing and failing on synthetic sheets, plus the Malam FY2025 scenarios "Cash-flow identity fails" (38,856,000 vs 3,798,000), "Equity identity fails" and "Balance sheet balances". Also verify that BS1 and BS5 pass for Leumi FY2024 (IS2 is `not_applicable` there: its FY2024 income statement holds net income only) and that BS1, BS5 and IS2 pass for Harel FY2025.
- [x] 3.2 Implement `not_applicable` for missing cells and for cells derived by a rule that embodies the check. Verify the "Derived common equity" scenario (Malam FY2023 BS5 is `not_applicable`, not `passed`).

## 4. Ratio engine

- [x] 4.1 Create `server/stock_analyzer/fin/ratios.py` with the `Ratio` registry and `compute(sheet, checks)` (design D6): exact arithmetic, averages with `avg_used`, missing-reason codes, confidence and derived inputs, delta and status. Verify tests in `server/tests/unit/test_fin_ratios.py` for "Malam gross margin" (0.1047), "ROE with an average" (≈ 10.03%), "Oldest year", "Missing input", "No prior year for growth", "Failed equity check", "Derived input" and "Change beyond the threshold".
- [x] 4.2 Declare the industrial, core and bank ratios with Hebrew names, groups, units, directions, thresholds and templates (design D6), and the reported pass-through ratios. Verify the "Registry entry", "Insurer ratios" (Harel: core only, no margins), "Bank ratios" (Leumi FY2024 loans/deposits 73.67%) and "CET1" (11.98%, basis `reported`) scenarios, and a test that each template gets exactly its listed ratio codes.
- [x] 4.3 Calibrate the thresholds on Malam's five years and record the final values in the registry. Verify the "Malam series" scenario (gross margin FY2025 is stable against FY2024).

## 5. Service, CLI and API

- [x] 5.1 Create `server/stock_analyzer/services/ratios.py` with `ratios(ctx, ticker, as_of=None)`, which resolves the company, loads cached financials, builds sheet, checks and ratios, and applies the contiguous year window from design D7. Add the `RatiosOut` models from design D8 to `services/models.py`. Verify tests in `server/tests/unit/test_services_ratios.py`: Malam, Leumi (no 2013 in the window) and Harel (FY2021 ROE averages with FY2020), plus "As-of date".
- [x] 5.2 Add a `ratios TICKER [--as-of] [--mode]` command to `server/stock_analyzer/cli.py` that prints ratios by group and year with low-confidence values marked, and update the module docstring's command list. Verify a test in `server/tests/unit/` for "CLI output" (cached mode, no network calls).
- [x] 5.3 Add `GET /api/companies/{ticker}/ratios` to `api/routers/companies.py`, calling `services/ratios.ratios`. Verify tests in `server/tests/api/test_api.py` for "Malam ratios", "Low-confidence value", "Financials not cached" and "Unsupported template", and that every value is a string or null (never a JSON float).
- [x] 5.4 Regenerate `server/openapi.json` with `server/scripts/export_openapi.py`. Document the endpoint, the `ratios` command and `template_not_supported` in `server/README.md`. Verify `test_openapi_lists_every_endpoint` passes and the documented command runs as written against the fixture data.

## 6. LLM tools

- [x] 6.1 Create `server/stock_analyzer/tools.py` with `AnalysisTools(ctx, ticker, as_of)`, `definitions` and `call(name, arguments)` for `get_ratios` and `get_financials` (design D9), computing the service result once per tool set. Verify tests in `server/tests/unit/test_tools.py` for "Definitions for the gateway", "Ticker not an argument", "Point in time", "One group", "Unknown code" (error result, no exception), "Selected fields" and "Ratio id" (`RATIO:gross_margin:2025`).
- [x] 6.2 Verify the definitions pass through the LLM gateway: a test with the real gateway on a mocked HTTP route (the fake LLM ignores `tools`) that `complete_json(..., tools=AnalysisTools(...).definitions)` sends them in the request. Add the parity test "Parity with the API" (same values, confidence and status as the endpoint for MLTM with the same `as_of`).

## 7. Web client

- [x] 7.1 Add `recharts@3` to `web/package.json`, run `npm run gen:api`, and add `api.ratios(ticker, mode, asOf)` to `web/src/api/client.ts`. Verify `npm install`, `npm run check:api` and `npm run build` pass.
- [x] 7.2 Create `web/src/features/ratios/RatiosPage.tsx` (lazy-loaded route `:ticker/ratios` in `main.tsx`, linked from the company page), with group sections, one LTR chart card per ratio, unit formatters in `lib/format.ts`, `connectNulls={false}`, low-confidence dots, a tooltip with missing reason, failed checks and derived inputs, a latest-value header with delta and status, and the "available by date" control (design D10). Verify `npm run lint` and `npm run build` pass, and that the ratios chunk is separate from the main bundle in the build output.
- [x] 7.3 Extend `web/e2e/ui-check.cjs` with checks for the web-client scenarios "Malam ratios" (years increase left to right), "Bank company" (Leumi: no margin charts), "Missing year" (no FY2021 point for the quick ratio), "Low-confidence value", "Latest value and change" and "As-of date". Verify the script reports PASS for each, against the dev server and an API with the fixture data cached.

## 8. Integration

- [x] 8.1 Run the full server suite (`uv run pytest` in `server/`) and the web build and lint, then run `openspec validate add-financial-ratios --strict`. Verify all pass.
- [ ] 8.2 With a local API on the state store, open the ratios view for MLTM, LUMI and HARL in cached mode and confirm that no provider credits are spent (the usage log shows no new `fr` misses). Verify by checking `usage_log` before and after.

## Workflow follow-up

- Archive the change after review, and sync the delta specs into the main specs.
