# FinancialFilings REST API — endpoints used by `fr_client.py`

Verified against the provider's OpenAPI document `GET https://api.financialreports.eu/api/schema/`
(title "FinancialFilings API", **version 1.4.0**, fetched 2026-11-10), plus real Malam (company 6901)
responses read during development. Re-check this file when the schema version changes.

## Common

| Item | Confirmed value |
|---|---|
| Base URL | `https://api.financialreports.eu` (paths have no `/api` prefix; only the schema lives at `/api/schema/`) |
| Auth | header `X-API-Key: <key>` on every request. Missing key → `403` with `{"detail", "type": "authentication_required", "resolution"}` |
| Billing headers | every billed response carries `X-Credits-Charged` and `X-Credits-Category`. The client logs the charged value, falling back to the documented price when the header is absent |
| Rate-limit headers | `X-RateLimit-Burst-Limit` (e.g. `50/second`), `X-RateLimit-Monthly-Limit`, `X-RateLimit-Monthly-Remaining`, `X-RateLimit-Monthly-Unit`. Strings, possibly non-numeric (`Unlimited`) |
| 429 | body describes the limit; header `Retry-After` in **seconds**. 429s are not billed |
| Pagination (lists) | `{count, next, previous, results}` with `page` / `page_size` |
| Errors | JSON `{"detail": ..., "type": ..., "resolution": ...}` for 4xx; 404 for unknown ids |

## Endpoints

### `search_companies(q)` → `GET /companies/`
- **Cost:** 1 credit.
- **Params used:** `search` (name incl. former names, ticker, LEI/ISIN prefix; case/accent-insensitive),
  `countries=IL` (ISO alpha-2, comma-separated), `view=full` (the default `summary` view has **no `ticker`**),
  `page_size`.
- **Fields read (full view `Company`):** `id`, `name`, `ticker`, `isins`, `primary_isin`, `country_code`.
- An unmatched search returns `200` with `results: []`, not an error.

### `list_filings(company_id)` → `GET /filings/`
- **Cost:** 1 credit.
- **Params used:** `company=<id>`, `type=10-K` (one filing-type code; unknown codes → 400),
  `ordering=-release_datetime`, `view=full`, `page_size=100`.
- **Why `view=full`:** the summary `FilingSummary` lacks `fiscal_year`, `fiscal_period` and `period_ending_date`.
- **Fields read (`Filing`):** `id`, `title`, `fiscal_year` (nullable), `fiscal_period`, `release_datetime`,
  `file_extension` (`PDF`, `HTM`, …), `file_size` (bytes, nullable), `document` (the file URL — named
  `document`, not `document_url`, in the full view; summary rows call it `document_url`), `viewer_url`,
  `processing_status`, `language.code`.
- **Observed for Malam:** FY2025 → 32935334 (PDF, 4,215,135 B) + 32935333 (HTM cover form);
  FY2024 → 63741657 (PDF, 4,614,691 B) + 63728804 (HTM) + 63741654 (HTM, title contains "iXBRL").
  The listing holds 35 10-K rows for Malam, so the client pages until `next` is null.

### `get_markdown(filing_id)` → `GET /filings/{id}/markdown/`
- **Cost:** 6 credits per call (12 for premium filing types), **whole or windowed**.
- **Response:** `text/markdown` body. Headers: `X-Total-Chars` (full document length, characters) on every
  response; `X-Next-Offset` only while characters remain after the returned window.
- **Params:** `offset` (default 0) and `limit` (≤ 200,000 chars per window). **Omitting both returns the whole
  document in one call** — the cheapest way to fetch a report (one billed call).
- **Client strategy:** one call without `offset`/`limit`; if the response still carries `X-Next-Offset`,
  follow it with `offset=<next>&limit=200000` until it disappears; then assert
  `len(text) == X-Total-Chars` (Python `str` length = Unicode code points) or fail without saving.
- **Observed:** Malam FY2025 = 390,912 chars (page style B), FY2024 = 410,512 chars (page style A).
- `404` → no Markdown for that filing.

### `get_financials(company_id)` → `GET /companies/{id}/financials/`
- **Cost:** 40 credits per call. Marked *Experimental* (may change without a version bump).
- **Params used:** `fiscal_period=FY`; all line items (omit `line_items`); second call adds `include=revisions`
  (**confirmed** in the `include` enum: `as_reported, preliminary, ratios, revisions, split_adjusted,
  standalone_quarters`). Also available: `as_of` (filing-date cutoff), `as_known_at`, `fiscal_year_from/to`,
  `statement_type` (`IS`/`BS`/`CFS`).
- **Response:** `{company_id, template, currency{code,name,symbol}, period_count, periods[]}`;
  each period `{fiscal_year, fiscal_period, period_start_date, period_end_date, statements[]}`;
  each statement `{statement_type, currency, currency_mismatch, source_filing{id, filing_type,
  release_datetime, document_url}, line_items[]}`;
  each line item `{code, name, statement_type (IS/BS/CFS/SUP), depth, parent_code, sort_order,
  value (decimal string, already scaled), raw_value (decimal string or null), scale ("units",
  "thousands", "millions", … or null), currency, available_at (datetime), revisions[] (with include)}`.
- `raw_value`/`scale` are `null` when the provider computed a figure; such values are not "as reported".
- **Observed for Malam:** currency ILS; FY2025 revenue `value` 4138004000.00 (raw 4138004000, scale units);
  FY2025 cost_of_revenue raw 3704618 × thousands; FY2023 values `available_at` 2024-06-13T17:12 (the
  iXBRL filing), although the FY2023 report was released 2024-03-20.

### `usage()` → `GET /usage/`
- **Cost:** free; never billed and not counted toward any quota.
- **Response:** sections that do not apply are `null`: `payg` (pay-as-you-go spend and caps),
  `free_credits` (monthly free pool), `requests` (request quota). The exact inner fields are not published
  in the schema, so the client keeps the body as a permissive dict and the API passes it through.

## Not used in Phase 1
`/filings/{id}/markdown/search/` (search one filing), `/filings/search/`, `/line-item-definitions/`
(Phase 3 code confirmation), `/companies/resolve/`, webhooks, watchlist.
