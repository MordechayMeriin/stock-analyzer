# Proposal

## Why

The home page can search the provider for any Israeli company, but a match that is not tracked only shows a "not tracked" label. The only way to track it is to edit `server/data/companies.yaml`, commit and redeploy. That is slow for local work and impossible from the hosted app, which has no persistent disk. Tracking a new company should be a step the user can take from the search result, with the same safeguards as other actions that spend provider credits.

## What Changes

- **Runtime-added companies.** Besides the version-controlled list in `companies.yaml`, the server keeps companies added at runtime in the state store: files under `DATA_DIR` locally, Postgres when `DATABASE_URL` is set. So they survive restarts and redeploys. The tracked list is the YAML list plus the added ones. Every place that resolves a ticker (filings, reports, financials, playground) sees both.
- **Add and remove endpoints.**
  - `POST /api/companies` adds a company from a provider search hit: provider id, ticker, Hebrew name, and optional English name and ISIN.
  - `DELETE /api/companies/{ticker}` stops tracking a company that was added at runtime.
  - Both need live mode. On a cached-only server (`ALLOW_LIVE=false`, the hosted default) they are refused, because adding a company is the first step towards spending credits on it.
  - Adding is refused when the ticker or the provider id is already tracked. Removing is refused for companies that come from `companies.yaml`.
- **Where each company comes from.** Each tracked company (in the list and the single-company endpoint) now reports its source: `registry` for the YAML list or `added`. The client uses this to decide which companies can be removed.
- **UI.**
  - Each untracked search hit gets an "add to tracking" action that opens a short form. Ticker and Hebrew name are prefilled from the hit and can be edited, since the provider may return no ticker or only a Latin name.
  - Companies added at runtime show a "stop tracking" action, with a confirmation.
  - In cached mode both actions are disabled, with an explanation.
- **CLI.** `stock-analyzer companies list | add | remove` call the same service functions. This is how an operator adds companies to the hosted store while the hosted API stays cached-only.
- **Not included:**
  - authentication
  - editing a tracked company's fields after adding it (remove it and add it again)
  - removing or changing companies from `companies.yaml` through the API
  - deleting cached reports, financials or logs when a company is removed (they stay keyed by ticker and are reused if it is added again)
  - fetching any filings automatically on add

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `filings-client`: "Tracked company registry" becomes the version-controlled list plus companies added at runtime, kept in the state store, each with its source. Covers uniqueness and resolving tickers through both.
- `analyzer-api`: "Company endpoints" gains adding and removing tracked companies (live mode only), the company source in responses, and the conflict errors.
- `web-client`: new requirements for adding a company from a search result and for removing a runtime-added company, both disabled in cached mode. The existing "Company and filing browser" requirement is unchanged.

## Impact

- **Server code:**
  - `companies.py`: the registry merges YAML and store entries.
  - `services/companies.py`: list, get, search, add and remove.
  - `services/filings.py`, `services/financials.py`, `services/reports.py`: resolve tickers through the merged registry.
  - `store/base.py`, `store/fs.py`, `store/pg.py`, `store/schema.sql`: a tracked-companies table and file.
  - `services/models.py`, `api/routers/companies.py`, `errors.py`, `api/errors.py`: new endpoints and error codes.
  - `cli.py`: a `companies` command group.
- **Web code:**
  - `web/src/api/client.ts`: POST and DELETE helpers.
  - `web/src/features/browser/CompaniesPage.tsx`: the add form, the remove action, cache invalidation.
  - `web/src/api/schema.d.ts`: regenerated.
- **Contract:** `server/openapi.json` gains two operations, and a `source` field on companies. Nothing is removed, so this is backwards compatible.
- **Hosted database:** the existing Supabase schema needs `stock-analyzer db init` re-run once to create the new table. The SQL is idempotent.
- **Ordering:** this builds on the in-progress `deploy-render-supabase-storage` change (state store, Postgres backend). That change should be archived first so the state-store spec exists in `openspec/specs/`.
