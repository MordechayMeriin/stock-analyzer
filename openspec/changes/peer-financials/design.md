# Design

## Context

The registry maps a tracked ticker to a FinancialReports issuer ID. The provider already supplies company profiles, a paginated company directory, and annual financial statements by issuer ID. The current local financials service resolves a tracked ticker before formatting statements. Most candidate peers may be untracked. [Company profile](https://docs.financialreports.eu/api-10374070) · [Directory filters](https://docs.financialreports.eu/api-10374069)

## Goals / Non-Goals

Give the analyst a reproducible industry cohort and enough context to interpret each issuer's statements. Assessing market power would require a market definition, evidence about private competitors, and market shares. The runner can establish which listed issuers the provider covers.

## Decisions

1. Put selection in `server/stock_analyzer/services/peers.py`. Give `FRClient` a profile read by ID and a paginated directory read filtered by `countries`, `listing_status=LISTED`, and the profile's `sub_industry.code` via `sub_industry`. Use full rows for ticker, country, class, and listing status. The service checks eligibility, deduplicates by issuer ID and sorts all eligible IDs before slicing. Choosing the first page would make the cohort depend on provider order.
2. Expose `stock-analyzer peer-financials TICKER --limit 5`, defaulting to five and the existing cached mode. Allow repeatable `--peer-country GB --peer-country DE` for additional markets. Normalize and deduplicate country codes, excluding IL from the foreign request. Always search Israel first using `countries=IL`, independently of the target's recorded country. Use one paginated country-filtered foreign search only when the caller named additional countries and places remain. Always report domestic eligible count before the limit and retain `no_domestic_matches` even if foreign peers are found.
3. Include issuer ID, name, ticker when available, country and `domestic` or `international` in each peer record. Include the target ID, its country when available, the default market IL, matched class and requested markets once per run. Provider ID ordering breaks ties reproducibly. Ordering conveys no judgement about operating scale. Leave size and margin comparisons to the consumer of the statements.
4. Fetch `GET /companies/{id}/financials/?fiscal_period=FY` for selected IDs through the existing client. Extract shared statement formatting from `services/financials.py` so an issuer identified by provider ID gets the same annual grouping and exact decimal serialization as a tracked issuer. Preserve distinct reporting currencies. An issuer with an empty annual series keeps its identity and empty statements. Propagate provider/cache errors through the runner's usual error path.
5. Implement the testing agent as a repeatable offline evaluator in the pytest suite. Invoke the real Typer entry point, match exact HTTP requests with respx, and compare its JSON with versioned, independently labelled cases. Keep a dated reviewer rationale and source for each business judgement. Record selected, accepted, unsuitable, unreviewed, and missed expected IDs per case. Report acceptance among reviewed selections with its denominator. An empty denominator yields an inapplicable rate. Keep benchmark labels outside production selection.

## Risks / Trade-offs

- A class can include operators with materially different activities. For example, a regulated grid operator and a merchant generator could have very different exposure to electricity prices. Evaluate foreign analogues against the target's activity, customers and regulatory model and record the reason for each judgement.
- A provider country identifies the issuer's recorded country. Issuers can operate elsewhere and private competitors can fall outside directory coverage. Describe the observed coverage and preserve short cohorts.
- Selecting across all pages costs directory reads. Complete discovery before fetching statements so `--limit` bounds the number of distinct issuers whose financials are requested.
