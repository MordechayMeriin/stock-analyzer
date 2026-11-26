# Design

## Context

See proposal.md (Why) for the failures. The current code relevant to this change:

- **`FRClient.list_filings`** (`ingest/fr_client.py`) pages through `GET /filings/?company=…&type=10-K&view=full` through the permanent cache. Each cached page is an `FRResponse` that carries `fetched_at`. `Filing` already parses `processing_status`, but nothing reads it.
- **`select_report` and `selected_by_year`** (`ingest/select.py`) filter candidates (PDF, no iXBRL, a title naming a periodic report) and take `max(file_size, id)`.
- **Four call sites** list filings and select a report, each with its own copy of the logic:
  - `services/filings.list_filings`: the API and browser listing
  - `services/filings.fetch`: the CLI `fetch`
  - `services/filings.company_filings`
  - `services/reports._ensure_raw`: a live report request from the API
- **A Markdown 404** becomes `ProviderNotFound` (`upstream_not_found`, HTTP 502). It is not cached, and the provider does not bill it (`X-Credits-Charged: 0` was observed).
- **The hosted API is cached-only.** Live calls come from the laptop CLI, or from a local live-mode server. So in the hosted app, a year's availability reflects the filing list from the last time it was cached.

## Goals / Non-Goals

**Goals:**
- One place that decides "the filing list to select from" and "the year's Markdown availability", used by all four call sites.
- No extra billed calls in cached mode, and at most one list refresh per company per request in live mode.

**Non-Goals:**
- Polling the provider in the background, or a scheduled job that refreshes filing lists.
- Changing the permanent-cache rule for anything other than the conditional list refresh.
- Showing the processing status of filings that were not selected, beyond passing the raw status through on each filing entry.

## Decisions

### 1. Availability is a derived four-value field, computed in `select.py`

`markdown_availability(filing) -> "available" | "unknown" | "processing" | "failed"`:
- `COMPLETED` is `available`.
- No status is `unknown`.
- `PENDING`, `QUEUED` and `PROCESSING` are `processing`.
- `FAILED` and `SKIPPED` are `failed`.
- Any other value is `unknown`.

The API also passes the raw `processing_status` through on each `FilingOut`, so a new provider value is visible without a code change.

*Alternative considered:* expose only the raw status and let the web client interpret it. That was rejected because it duplicates the mapping in the CLI and the web client, and the selection ranking needs the mapping on the server anyway.

### 2. Rank candidates by availability first, then by size

The sort key becomes `(availability_rank, file_size, id)` with `available = unknown > processing > failed`.

`unknown` ranks equal to `available`, following the provider's guidance that a missing status means unknown, not "not ready". Selection still picks a filing when every candidate is unprocessed. A year with candidates therefore always has a selected filing (keeping the "exactly one full report" contract), and the year's availability tells the reader whether its text can be fetched.

*Alternative considered:* fail selection when no candidate is processed. That was rejected because it loses which filing the year is waiting for, and it merges two different states ("no report filed" and "report not processed") into one error.

### 3. Refresh the filing list only when it matters, and only once

Add a new service helper, `filings_for(ctx, company, needed_years=None) -> list[Filing]`, which every call site uses:

1. Read the list through the cache, as today.
2. If `ctx.mode == "live"`, compute the selection for the needed years (all years when `needed_years` is `None`, which is what the listing endpoint passes). Continue only if any selected filing is not `available`.
3. Continue only if the cached list is more than 24 hours old, judged by the `fetched_at` of the first cached page. `FRClient` gets a small `cached_at(path, params)` accessor so the services do not reach into cache keys.
4. If so, call `list_filings` once with `refresh=True`, which re-fetches every page and overwrites the cache. Return the fresh list.

The 24-hour threshold is a module constant, not a setting. The provider's backfill moves on a scale of days to months, so a finer threshold would only spend credits.

`unknown` does not trigger a refresh. Only `processing` and `failed` do, because these are the states a newer list can resolve.

*Alternative considered:* always try the Markdown endpoint (404s are free) and skip list refreshes. That was rejected because it cannot fix the ranking when a larger filing becomes `COMPLETED`, and the browser would keep showing a stale "processing".

*Alternative considered:* an explicit `refresh` query parameter on the filings endpoint. It was deferred: the automatic rule covers the need without a new UI control, and the CLI's `fetch --refresh` already exists for a full re-download.

### 4. A new error, `ReportNotProcessed` (`report_not_processed`, HTTP 409)

It is raised in two cases:
- **Before calling the Markdown endpoint,** when the selected filing (after the conditional refresh) is `processing` or `failed`. The provider guidance says no Markdown exists in that state, so the app saves the call.
- **When the Markdown endpoint answers 404** for a filing that is not `COMPLETED`. This covers `unknown` filings that turn out to be unprocessed.

A 404 for a `COMPLETED` filing still raises `ProviderNotFound`.

The status is 409, like `not_cached`: the request is valid, but the data is not ready. It is neither 404 (the company, year and filing all exist) nor 502 (the provider is behaving as documented).

*Alternative considered:* always call the Markdown endpoint, even for `processing`. It was rejected: the call is free, but a predictable failure doesn't need a network round-trip. The conditional list refresh already covers a provider that has finished in the meantime.

### 5. Web client: availability drives the year card

`YearCard` reads `markdown_availability` and `report_cached`:
- **Cached:** unchanged.
- **Not cached and `processing` or `failed`:** a warning badge ("טרם עובד אצל הספק" / "הספק לא הצליח להמיר"), a one-line explanation, and no read or playground buttons.
- **Otherwise:** unchanged.

The Hebrew copy follows the existing badge style. The error view for `report_not_processed` needs no special case beyond the generic error state. It is reached only by a deep link to an unprocessed year.

## Risks / Trade-offs

- **[Provider list is stale within 24 h]** → A report finished minutes ago is fetchable only after the threshold passes, or with `fetch --refresh`. This is acceptable for reports that took months to process.
- **[Refresh re-bills every page]** → Lists are one page for every tracked company (at most 51 rows, page size 100). The cost is about 1 credit per company per day, and only in live mode.
- **[Ranking flips a previously cached selection]** → If a smaller `COMPLETED` filing now outranks a larger `QUEUED` one, the year's selected id can differ from a cached report's filing id. `report_cached` already compares ids, so the browser would show "not cached" until the year is fetched again. No current tracked year is affected: every cached report is `COMPLETED` and was already the largest candidate.
- **[New provider status values]** → They map to `unknown`, which neither blocks a fetch nor triggers a refresh. The raw value is still shown per filing.
- **[Requirements also modified by the unarchived `generalize-report-parsing`]** ("Filing endpoints", "Company and filing browser") → Archive that change before this one. These deltas are written on its text.

## Migration Plan

- No data migration. The new fields are computed on read, and cached filing lists already hold `processing_status`.
- Regenerate `server/openapi.json` and `web/src/api/schema.d.ts`. The changes only add things, so existing clients keep working.
- Rollback: revert the change. No stored state depends on it.
