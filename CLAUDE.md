# CLAUDE.md

## Check Supabase before spending provider credits

Data that has already been fetched lives in the hosted state store. Look there **before** calling
FinancialFilings, whose calls cost credits: financials 40 per request, report markdown 12, metadata 1.
The free pool is 500 credits a month, and `usage_retrieve` checks the balance at no cost.

- **Where:** Supabase project "Twin" (ref `uuphsgiqaswqtntdkqgp`), schema `stock_analyzer`. It can be
  read through the Supabase MCP connector (`execute_sql`) even when `DATABASE_URL` is not set locally.
- **Tables:**
  - `tracked_companies`: the tracked tickers and `fr_company_id`s. The list changes (it now
    includes banks and insurers), so query it rather than assuming `server/data/companies.yaml` is
    complete.
  - `reports`: one row per (ticker, fiscal_year) with the full report markdown in `text`.
  - `kv_cache`: raw provider responses (namespace `fr`) and LLM responses (namespace `llm`). The
    provider payload is a JSON *string* in `value->>'body'`, next to `credits` and `fetched_at`.
    Financials responses contain `line_items`; find them with
    `where namespace='fr' and value->>'body' like '%line_items%'` and read `"company_id"` from the body.
  - `financials_snapshots`, `usage_log`.
- Reports are 1-3 MB each, so read slices (`substring(text from 1 for 4000)`) instead of whole
  rows.
- Fetch live only when the data is not stored, and say how many credits the call will cost first.
- **Never pass `--no-financials` to `stock-analyzer fetch`.** Every fetch must also save the
  company's financials. Earlier fetches that skipped them are why only Malam had financials in
  the store.
- Fetch through the app (the `stock-analyzer` CLI or `FRClient`), not through the FinancialFilings
  MCP connector. Connector calls cost the same credits but never reach the app's cache.
