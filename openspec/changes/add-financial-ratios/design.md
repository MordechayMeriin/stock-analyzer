# Design

## Context

See proposal.md for motivation and specs/ for the requirements.

- `fin/normalize.py` turns the provider's financials response into `FinValue` records (exact `Decimal`,
  point-in-time `available_at`, one currency per company) and drops the response's `template` field.
  `services/financials.py` groups them for the existing financials table; `as_of` filtering already exists.
- Cached financials today: Malam (`industrial`, 14 periods in the state-store cache), Leumi (`bank`: FY2025,
  2024, 2023 and a stray 2013) and Harel (`insurer`: FY2017–2025). The Malam test fixture
  (`tests/fixtures/mltm_financials.json`) predates the `template` field and holds only 5 periods.
- Coverage findings that shape the design (from exploration):
  - industrial: big totals are reported in every year; detail items (debt parts, receivables, capex,
    dividends, SG&A) only in some years;
  - Leumi has no revenue or net interest income at all; FY2024 and FY2023 income statements hold only net
    income; FY2025 comes from an interim report's comparative column;
  - Harel has high-trust data for 9 years, but only top-level lines (no premiums or claims);
  - provider data is internally inconsistent at times: Malam FY2025 `total_equity` equals common equity
    *minus* minority interest, and Malam's minority interest is negative in FY2023.
- The LLM gateway already accepts `tools` on `complete_json`. There is no agent loop yet (plan.md §5.3);
  this change provides the tools, not the loop.
- The web client has no chart library.

## Goals / Non-Goals

**Goals:**
- A pure, I/O-free computation core (`fin/`) that takes normalized values and returns canonical sheet,
  check results and ratio series, so the CLI, API, tools and tests all share it.
- Registries (canonical fields, checks, ratios) declared as data, so adding a field source (option B),
  a check or a ratio is a one-entry change.
- Honest output: every number traceable to its inputs; missing and low-confidence values explicit.

**Non-Goals:**
- An agent loop, evidence registry or claim verification (later committee work).
- Persisting computed ratios: they are recomputed from cached financials on every request. The data is a
  few hundred values, so caching is unnecessary.
- Plausibility-range checks (plan.md PL1) and the checks that need more line items than we have
  (IS3, IS4, BS4, CF2); they join the check registry later.

## Decisions

### D1. Layering
```
 services/financials.fin_values()  -->  fin/canonical.build_sheet(values, template)  -->  Sheet
                                         fin/checks.run_checks(sheet)                 -->  CheckResults
                                         fin/ratios.compute(sheet, checks)            -->  RatioSeries[]
 services/ratios.ratios(ctx, ticker, as_of)   <-- used by CLI `ratios`, API route, tools.py
```
`fin/` modules are pure functions over value lists (no ctx, no store), like `fin/normalize.py` today.
`services/ratios.py` does the I/O, `as_of` filtering, year window and response model.
*Alternative:* computing ratios inside `services/financials.py`. Rejected: tools and tests would need a
ctx, and the core would mix I/O with arithmetic.

### D2. Template comes from the response
`normalize.py` gains `financials_template(data) -> str | None`, and `services/financials.py` returns the
template next to the values. `normalize_financials` keeps its signature, so existing callers are untouched.
A template with no canonical field set raises a new `TemplateNotSupported` (`template_not_supported`,
HTTP 422); `None` (old cached responses) is treated the same way, with the message saying the cached
financials predate the template field and need a refetch.
*Alternative:* inferring the template from which codes are present. Rejected: guesswork, when the provider
states it.

### D3. Canonical fields as data
Each template has an ordered list of `Field(name, statement, label_he, sources)`. A source is one of:
- `Code("total_common_equity")`: the provider code;
- `Rule(id, inputs, fn, embodies=check_id | None)`: a derivation over other canonical fields, with `fn` a
  small Python callable over `Decimal`s.

Resolution walks the sources in order and stops at the first value. Rules may use fields resolved later in
the list (resolution is lazy and memoized per year), and a cycle raises at registry-load time.
*Alternative:* string formulas with a parser. Rejected: a parser to maintain for a dozen rules, and Python
callables are type-checked and testable.

Initial field sets:
- **industrial:** revenue, cost_of_revenue, gross_profit, operating_income, ebit, ebitda, d_and_a,
  net_income_parent, net_income_consolidated, minority_interest_in_earnings, basic_eps, cash,
  cash_and_st_investments, receivables, inventory, current_assets, total_assets, current_liabilities,
  total_liabilities, minority_interest, common_equity, total_equity, current_debt, noncurrent_debt,
  total_debt, net_debt, cfo, cfi, cff, capex, net_change_in_cash, net_income_cf, dividends_paid.
- **bank:** total_assets, total_liabilities, total_equity, common_equity, minority_interest,
  net_income_parent, net_income_consolidated, basic_eps, cfo, cash_and_central_bank, loans_net,
  gross_loans, customer_deposits, loan_loss_allowance, nonperforming_loans, risk_weighted_assets,
  cet1_ratio, tier1_ratio, total_capital_ratio, leverage_ratio.
- **insurer:** total_assets, total_liabilities, total_equity, common_equity, minority_interest,
  net_income_parent, net_income_consolidated, minority_interest_in_earnings, ebt, basic_eps, cash, cfo,
  cfi, cff.

Rules: `cost_of_revenue = revenue − gross_profit` and `gross_profit = revenue − cost_of_revenue` (embody
IS1); `common_equity = total_equity − minority_interest` (BS5);
`net_income_parent = net_income_consolidated − minority_interest_in_earnings` (IS2);
`ebitda = ebit + d_and_a`; `total_debt = current_debt + noncurrent_debt` (BS2), with `current_debt` and
`noncurrent_debt` falling back to sums of their component codes;
`gross_loans = loans_net + loan_loss_allowance`. `net_change_in_cash` is reported only: deriving it from
CFO + CFI + CFF would hide exactly the CF1 failures we know exist.

### D4. Cells and provenance
`Cell(value | None, basis, source, inputs, source_filing_id, source_filing_type, available_at)`. A derived
cell's `available_at` is the max of its inputs' (spec: Cell provenance), and its filing id is the inputs'
when they agree, else none. `source_filing_type` is kept so a value taken from an interim report's
comparative column (Leumi FY2025) can carry a note in the ratio output, without changing confidence.

### D5. Checks
`Check(id, templates, cells, test, tolerance)`. This change ships eight: BS1 assets = liabilities + equity;
BS2 debt = current + non-current; BS3 net debt = debt − cash and short-term investments; BS5 equity ≈
common equity + minority interest; IS1 gross profit = revenue − cost of revenue; IS2 parent net income =
consolidated − minority share; CF1 CFO + CFI + CFF ≈ change in cash; CF3 cash-flow net income =
consolidated net income.
- Tolerance: `|difference| ≤ max(0.5% × largest |term|, 1,000 base units)`. Equalities like BS1 still
  pass with rounding differences between statements reported in thousands and in units.
- `not_applicable` when a needed cell is missing, or when a cell was derived by a rule whose `embodies`
  equals the check id (spec: Checks are not satisfied by derivation).
- Expected on the Malam fixture: CF1 and BS5 fail in FY2025 (plan.md §3.4 also lists CF2, IS3 and BS4,
  which are deferred).

### D6. Ratio registry and arithmetic
`Ratio(code, name_he, group, unit, direction, threshold, templates, inputs, avg_inputs, fn)`.
- Templates: `core` ratios list all three templates; industrial-only and bank-only ratios list one.
- Reported ratios (CET1 etc.) are registry entries whose `fn` returns the canonical cell unchanged, with
  basis `reported`.
- `Decimal` with the default 28-digit context. Values are serialized quantized to 6 decimal places
  (fractions for percent: 0.104706). Deltas use the ratio's unit: percentage points for percent, absolute
  for ratio and days, relative change for amounts.
- Averages: for each `avg_input`, if the year before exists in the sheet with a value, use
  (opening + closing) / 2 and set `avg_used`; otherwise closing only.
- Missing reasons are fixed codes plus a Hebrew message: `missing_input:<field>`, `zero_denominator`,
  `negative_denominator`, `no_prior_year`.
- Confidence: `low` if any input cell (including the opening-year cells used for an average) is in a
  failed check's `cells` that year, or is derived. The derived-input case keeps a single confidence level
  but is listed separately (`derived_inputs`), so the UI can explain it.
- Status: `|delta| < threshold` gives stable; otherwise improved or deteriorated by direction, or changed
  for neutral ratios; NA when either year is missing.
- Initial thresholds come from plan.md §3.3 where given (gross margin 0.5pp, ROE 1.5pp, ROA 0.5pp,
  current ratio 0.1, debt/equity 0.1, equity/assets 2pp, CFO/NI 0.2, FCF 10% relative, FCF margin 0.5pp);
  the others start at 0.5pp for margins, 3pp for growth and 2pp for bank ratios.

### D7. Year window
Ratios are computed over every fiscal year in the sheet (averages and growth need the year before), then the
response keeps the newest `fin_max_years` (5) **contiguous** calendar years ending at the latest year. That
drops Leumi's stray 2013 and lets Harel's FY2021 average with FY2020. "Prior year" always means exactly
fiscal year − 1.

### D8. Output shapes
- API `RatiosOut { ticker, template, currency, years, as_of, groups: [{ group, label, ratios: [RatioSeriesOut] }], checks: { "<fy>": [CheckOut] } }`,
  with `RatioSeriesOut { code, name_he, unit, direction, values: { "<fy>": RatioValueOut } }` and
  `RatioValueOut { value: str | None, missing_reason, confidence, failed_checks, derived_inputs, avg_used, inputs: { field: str }, delta: str | None, status, notes }`.
  The `checks` map feeds the details in the chart and a later data-quality panel.
- Tool output is a compact projection of the same service result (D9), so API and tools cannot diverge.

### D9. Tools
`tools.py`: `AnalysisTools(ctx, ticker, as_of)` with `definitions` (the function-tool JSON the gateway
forwards: `{"type": "function", "function": {name, description, parameters}}`) and
`call(name, arguments) -> dict`.
- `get_ratios(group?, codes?)` returns `{ ratios: [{ code, name_he, unit, values: [{ id, fy, value, confidence, failed_checks, status, missing_reason }] }] }`.
- `get_financials(fields?)` returns `{ fields: [{ field, label_he, values: [{ id, fy, value, basis }] }] }`.
- Unknown group, code or field gives `{ "error": "..." }` rather than raising (spec: Unknown code).
- Ids: `RATIO:{code}:{fy}` and `FIN:{field}:{fy}`.
- Both call `services/ratios.py`; the service result is computed once per tool set and reused.

### D10. Web chart
Recharts (`recharts@3`, React 19 compatible) `LineChart` per ratio, small multiples in a grid per group.
- Chart containers are `dir="ltr"` so years run left to right (spec: Ratios view); labels and tooltips stay
  RTL Hebrew inside.
- `connectNulls={false}`, with missing years kept as `null` points, so the line breaks (spec: Gaps).
- A custom dot draws low-confidence points hollow with a warning color. The tooltip lists missing reason,
  failed checks and derived inputs.
- Header per card: latest value, delta and a status arrow. Formatting reuses `lib/format.ts`, plus percent
  and days formatters.
- Route `:ticker/ratios` next to `:ticker/financials`, linked from the company page.

*Alternatives:* hand-written SVG (no dependency, but axes, tooltips and responsiveness to build and test);
ECharts or visx (heavier, or lower-level than needed).

### D11. Fixtures
- Refresh `tests/fixtures/mltm_financials.json` from the state-store cache entry, so it carries `template`.
- Add `lumi_financials.json` and `harl_financials.json` from the cached Leumi and Harel responses
  (51 KB and 112 KB).
- All three are read from Supabase with read-only SQL: no provider credits.
- Existing tests that read the Malam fixture are rerun; the extra older periods are outside the 5-year
  window.

## Risks / Trade-offs

- [Provider sign conventions are inconsistent (Malam's minority interest sign, equity = common − MI)] →
  BS5 flags it and every ratio using those cells is `low`. No silent "fixing" of signs in this change.
- [Derivations can launder bad inputs into plausible-looking values] → derived cells mark ratios `low`
  and list the derived inputs, and checks embodied by a rule become `not_applicable`, never `passed`.
- [Leumi FY2025 comes from an interim report's comparative column] → `source_filing_type` produces a note
  on affected values; a later change can prefer annual filings.
- [Thresholds are first guesses] → they live in the registry. Calibrating them on Malam is a tuning task
  that changes no spec.
- [Debt fallback may not match the provider's own `total_debt_bs` definition (leases in or out)] →
  calibrate the component sum on Malam FY2025, where both exist, before relying on the fallback.
- [Recharts adds about 100 KB gzipped to the client bundle] → load the ratios route lazily, so it doesn't
  affect the reader's first load.
- [Old cached financials without `template`] → a clear `template_not_supported` message telling the user
  to refetch, instead of guessing.

## Migration Plan

Additive only: new modules, a new endpoint and a new route. No stored data changes. Deploy the server
first (the client calls the new endpoint only from the new view). Regenerate `server/openapi.json` and
`web/src/api/schema.d.ts` in the same change. Rollback is reverting the change; nothing to clean up.

## Open Questions

- Final change thresholds per ratio: calibrated on Malam during implementation; changes only registry
  values.
