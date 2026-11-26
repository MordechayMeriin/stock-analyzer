# Proposal

## Why

The analyst needs basic financial ratios for each tracked company, charted year over year, and the
same numbers must be available to LLM agents as tool calls. The provider's line items share one code
set, but coverage is uneven: big totals are reported every year, while details (debt parts, receivables,
capex, dividends) appear in some years only, and banks and insurers use different templates with their
own items. Computing ratios straight from raw codes would give charts with one to three points and
silent gaps, so the values must first be standardized into a canonical sheet per template, checked for
consistency, and only then turned into ratios.

## What Changes

- **Canonical sheet per template.** For each company and fiscal year, build a fixed set of canonical
  fields chosen by the provider's template (`industrial`, `bank`, `insurer`). Each field is resolved from
  an ordered list of sources: the reported code, then fallback codes, then derivation rules (for example
  common equity = total equity − minority interest). Every cell records its basis (reported, derived with
  the rule id, or missing) and its inputs. Provider data only in this change; values read from the reports'
  statement tables join later as one more source.
- **Data-quality checks.** About eight accounting-identity checks (balance sheet balances, cash-flow
  components sum to the change in cash, equity ≈ common equity + minority interest, and similar) run
  on the canonical sheet before any ratio. A ratio whose inputs take part in a failed check gets
  `confidence: low` and the ids of the failed checks.
- **Ratio registry and engine.** A declarative registry of ratios (code, Hebrew name, group, formula,
  inputs, unit, direction, applicable templates), computed with exact decimals:
  - industrial: 15 basic ratios (margins, growth, ROE/ROA, current and quick ratio, equity/assets,
    debt/equity, CFO/net income, free cash flow and FCF margin);
  - every template: core ratios (ROE, ROA, equity/assets, net income growth, EPS growth, CFO/net income);
  - banks: loans/deposits, non-performing loans/loans, loan-loss coverage, and the capital ratios the
    provider reports (CET1, Tier 1, total capital, leverage), passed through as reported.
  Balance-sheet denominators use the average of opening and closing values when both exist. A ratio
  that cannot be computed is returned as missing with a reason, never estimated.
- **Ratio series.** One output shape per ratio: a value per fiscal year with basis, confidence, notes, and
  the change from the previous year. Point-in-time `as_of` applies to the inputs.
- **CLI, API and web.** A `ratios` CLI command and a `GET /api/companies/{ticker}/ratios` endpoint
  return the same series. The web client gets a ratios view with one year-over-year line chart per ratio,
  grouped, with visible gaps for missing years and marked low-confidence points.
- **LLM tools.** Tool definitions `get_ratios` and `get_financials` that return the same series in a
  compact form with citable ids (`RATIO:{code}:{fy}`, `FIN:{field}:{fy}`), bound to a ticker and `as_of`,
  so agents read numbers instead of computing them.
- **Financial values carry the template.** Normalization keeps the provider's template so the canonical
  sheet and registry can be chosen.

Assumption recorded during planning: the data-quality checks are included in this change (recommended
in exploration; the user had not yet confirmed). They can be removed without affecting the rest.

Out of scope: reading statement tables from the reports (option B), restatements, management's
explanations, the change feed, valuation ratios (no share prices), insurer-specific ratios such as the
combined ratio (the provider has no premiums or claims for Harel), and bank/insurer report parsing.

## Capabilities

### New Capabilities
- `canonical-financials`: template-aware canonical sheet built from normalized values, with per-cell
  provenance and the data-quality checks run on it.
- `financial-ratios`: the ratio registry, ratio computation over the canonical sheet, and year-over-year
  ratio series with confidence and reasons.
- `analysis-tools`: LLM tool definitions over local data (`get_ratios`, `get_financials`), bound to a
  ticker and `as_of`, returning citable ids.

### Modified Capabilities
- `financial-data`: normalized values keep the provider's template for the company.
- `analyzer-api`: adds the ratios endpoint.
- `web-client`: adds the ratios view with year-over-year charts.

## Impact

- Server: new `stock_analyzer/fin/canonical.py`, `fin/checks.py`, `fin/ratios.py`, `services/ratios.py`,
  `tools.py`; small change in `fin/normalize.py`; new CLI command in `cli.py`; new route in
  `api/routers/companies.py`; models in `services/models.py`; `server/openapi.json` regenerated.
- Web: new `features/ratios/` view and route, `api/client.ts` call, regenerated `api/schema.d.ts`, and a
  chart library dependency (Recharts).
- Data: reads cached financials only (Malam, Leumi and Harel are cached in the state store today). No
  provider credits are spent by computing ratios.
- Tests: new unit tests with saved financials fixtures for an industrial company (Malam), a bank (Leumi)
  and an insurer (Harel), plus API and web tests.
