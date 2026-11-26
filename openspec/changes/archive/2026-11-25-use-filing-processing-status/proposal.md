# Proposal

## Why

Some reports cannot be fetched at all. FinancialFilings has not converted the PDF to Markdown, so the Markdown endpoint answers 404. The provider's filing list says so in advance with `processing_status`, which the app parses and then ignores.

The failures seen in the tracked companies (state store, 2026-11-25):
- **Rami Levy FY2024:** filing 61337033 is `QUEUED`. Its Markdown request was tried 7 times, all 404.
- **Delek Group FY2023:** filing 61330467 is `QUEUED`. Its Markdown request was tried 4 times, all 404.
- **Not available beyond those:** Rami Levy FY2019–FY2024 and Delek FY2019–FY2023 have only `QUEUED` periodic PDFs.

The provider added these as backfilled filings on 2026-09-24, and two months later they are still queued. Requesting them again does not speed anything up. Today the browser offers these years like any other, and the user learns otherwise only from a raw `upstream_not_found` error after clicking.

## What Changes

- **Processing status in the filing list.** Each filing carries the provider's processing status. Each fiscal year also shows the Markdown availability of its selected report:
  - `available`: the status is `COMPLETED`
  - `unknown`: there is no status
  - `processing`: `PENDING`, `QUEUED` or `PROCESSING`
  - `failed`: `FAILED` or `SKIPPED`
- **Selection prefers convertible files.** Among a year's periodic-report PDFs, a filing whose Markdown is `available` or `unknown` wins over one that is `processing` or `failed`, even if it is smaller. Within the same availability, the largest file still wins. A year whose candidates are all unprocessed still selects one, so the browser can show which filing it is waiting for.
- **A clear error instead of a raw 404.** Fetching a report whose provider Markdown does not exist yet fails with a new error code, `report_not_processed`. The message names the company, year, filing and provider status. It is also used when the Markdown endpoint answers 404 for a filing whose status is not `COMPLETED`.
- **Stale filing lists are refreshed when it matters.** In live mode, the app asks the provider for a company's filing list again (about 1 credit) when the selected report of a year it needs is not `available` and the cached list is more than a day old. So a filing the provider has finished in the meantime becomes fetchable without a manual refresh.
- **Web client.** A year whose report the provider has not processed shows "the provider hasn't processed this report yet" (or "the provider couldn't convert this report") instead of offering to read it. If that year's report is already cached, it stays readable.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `filings-client`:
  - "Annual report filings listing" adds the processing status.
  - "Complete report Markdown retrieval" adds the not-processed failure.
  - New requirements: "Selection prefers processed filings" (ranks by availability before the largest-file rule) and "Filing list refresh for unprocessed reports".
- `analyzer-api`:
  - "Filing endpoints" exposes each filing's processing status and each year's Markdown availability.
  - "Consistent error responses" adds the `report_not_processed` code.
- `web-client`: "Company and filing browser" shows unprocessed years as unavailable rather than readable.

## Impact

- **Server:**
  - `stock_analyzer/ingest/select.py`: ranking and availability mapping.
  - `stock_analyzer/ingest/fr_client.py`: filing-list age and conditional refresh.
  - `stock_analyzer/services/filings.py` and `services/reports.py`: the year's availability, the error, and the refresh in live fetches.
  - `stock_analyzer/services/models.py`: new fields on `FilingOut` and `FiscalYearFilings`.
  - `stock_analyzer/errors.py` and `api/errors.py`: the new code and its HTTP status.
  - `server/openapi.json` is regenerated.
- **Web:** `web/src/api/schema.d.ts` is regenerated, and `features/browser/CompanyPage.tsx` gets the new year states.
- **API contract:** the changes only add things. New response fields and one new error code. Nothing is removed.
- **Credits:** at most about 1 extra credit per company per day, and only in live mode. Markdown 404s are not billed.
- **Ordering:** this change modifies requirements that the completed but unarchived `generalize-report-parsing` change also modifies ("Filing endpoints", "Company and filing browser"). Its deltas are built on that change's text, so archive it first.
- **Out of scope:** getting the text of unprocessed reports some other way (downloading and converting the PDF ourselves), and asking the provider to prioritise the backfill.
