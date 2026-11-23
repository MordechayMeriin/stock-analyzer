# Design

## Context

See proposal.md for the motivation. The current state, as found in the code:

- **Registry.** `companies.py` loads `TrackedCompany` rows from `settings.companies_file` (YAML), cached by file mtime. `resolve_ticker(path, ticker)` is called directly by `services/companies.py`, `services/filings.py` (3×), `services/financials.py` (2×) and `services/reports.py` (2×), and by `tests/unit/test_select.py`. No caller has a `Ctx` handy at the registry layer; they all pass `ctx.settings.companies_file`.
- **Store.** `store/base.py` defines the `Store` protocol, implemented by `FsStore` (files under `DATA_DIR`) and `PgStore` (schema `stock_analyzer`, queries in a `_q` dict, idempotent `schema.sql` applied by `stock-analyzer db init`). `PgStore._check_schema` only looks for `kv_cache`. A missing table surfaces as `StorageNotInitialized` (`configuration_error`, 503).
- **Mode gate.** `Ctx.__post_init__` already refuses `mode="live"` when `ALLOW_LIVE=false` (`LiveModeDisabled`, 403). Nothing yet refuses a *cached* request for an operation that only makes sense live.
- **API/web.** All company routes are GET. CORS allows only `GET, POST`. The web client has a `get` helper and a POST-based SSE helper, and no React Query mutations yet. `CompaniesPage.tsx` shows untracked hits with a static "לא במעקב" label.
- **Search hits.** These carry `fr_company_id`, `name` (often the Latin name), optional `ticker`, `isin` and `tracked_ticker`.

## Goals / Non-Goals

**Goals:**
- One merged registry that every ticker lookup goes through, so an added company works everywhere a YAML company does.
- The same behaviour on the fs and Postgres backends, covered by the existing store contract suite.
- No change to how the YAML list is maintained or reviewed.

**Non-Goals:**
- Verifying the submitted company against the provider at add time (see D5).
- Concurrency control beyond what a unique constraint gives (single-user tool).

## Decisions

### D1. Added companies live in the state store, not in the YAML file
A new store surface: `list_tracked() -> list[TrackedCompany]`, `add_tracked(company) -> None` and `remove_tracked(ticker) -> bool`.
- **fs:** `DATA_DIR/companies_added.json`, a JSON array written to a temp file and then `replace`d (the same pattern as `save_report`), guarded by the existing per-path lock.
- **Postgres:** table `stock_analyzer.tracked_companies (ticker text primary key, fr_company_id bigint unique not null, name_he text not null, name_en text, isin text, added_at timestamptz default now())`, with RLS enabled and the same revokes as the other tables.

*Alternative:* write back to `companies.yaml`. Rejected: Render's disk is ephemeral, and a server writing to a git-tracked file creates surprise diffs.
*Alternative:* move the whole registry into the store. Rejected: the YAML list is the reviewed baseline the tests and fixtures depend on.

### D2. Merge rule: YAML first, store entries that don't collide
`load_registry(settings, store) -> list[TrackedCompany]` returns the YAML rows (`source="registry"`), then the store rows (`source="added"`) whose ticker (case-insensitive) and `fr_company_id` are not already present. Store rows that do collide are skipped and logged once as a warning; they are not deleted. `TrackedCompany` gains `source: Literal["registry", "added"] = "registry"`.

Uniqueness is enforced at add time against the merged view (service layer) and, for added-vs-added, by the table's primary key and unique constraint (Postgres) or the in-file check (fs). The YAML-wins rule only matters if someone later commits a company that was also added at runtime.

### D3. Ticker resolution goes through a context-aware function
Replace `resolve_ticker(path, ticker)` with `resolve_company(ctx, ticker)` in `services/companies.py`, built on `load_registry(ctx.settings, ctx.store)`. Update the seven service call sites. Keep `companies.load_companies(path)` for YAML-only reads (tests, and the merge itself).

*Alternative:* pass the store into `resolve_ticker`. Rejected: it pushes store plumbing into a module that is deliberately I/O-light, and every caller already has `ctx`.

Cost: listing companies or resolving a ticker now also reads the store. On Postgres that is one indexed query per request. The YAML part keeps its mtime cache, and the store part is not cached, so a removal is visible immediately.

### D4. Live-only gate as a service precondition
Add `LiveModeRequired(AnalyzerError)` with code `live_required` (403). `services.companies.add` and `remove` call a small `require_live(ctx)` helper first. The server-level refusal (`live_disabled`) already comes from `Ctx` before the service runs, which satisfies the "cached-only server" scenario with no extra code.

The CLI `companies add/remove` builds its `Ctx` with `mode="live"` by default. So on a developer machine with `ALLOW_LIVE=true` (the local default) it works, and against the hosted `DATABASE_URL` it writes straight to the shared store.

*Alternative:* a separate `ALLOW_REGISTRY_EDITS` flag. Rejected by the user in favour of reusing the live switch.

### D5. Trust the submitted fields and validate their shape
`POST /api/companies` takes `{fr_company_id: int > 0, ticker: str, name_he: str (1–200 chars, trimmed), name_en?: str, isin?: str (12 chars, [A-Z]{2}[A-Z0-9]{9}[0-9])}`. The ticker matches `^[A-Za-z0-9.\-]{1,15}$` and is stored upper-cased. The server does not re-fetch the provider company.

*Alternative:* look up `fr_company_id` with the provider before saving. Rejected for now: it needs a new client method and an extra billed call per add, the endpoint is already limited to live mode, and a wrong id shows up immediately as empty filings. It can be added later without a spec change.

### D6. API shape and errors
- `POST /api/companies?mode=live`: 201 with `CompanyOut`.
- `DELETE /api/companies/{ticker}?mode=live`: 204.
- `CompanyOut` gains `source`.
- New codes: `live_required` (403), `company_already_tracked` (409, the message names the existing ticker), `company_not_removable` (409).
- Add `DELETE` to CORS `allow_methods`.
- Regenerate `server/openapi.json` and `web/src/api/schema.d.ts`. `scripts/check-api-types.mjs` guards the drift.

### D7. Web: React Query mutations and an inline form
- `client.ts` gains `send<T>(method, path, query, body?)`, sharing the error mapping, and `api.addCompany(input, mode)` / `api.removeCompany(ticker, mode)`.
- `CompaniesPage.tsx`:
  - Each untracked hit gets an "הוסף למעקב" button that expands an inline form under the row. The form has the ticker (prefilled from `hit.ticker`), the Hebrew name (prefilled from `hit.name`), and the English name (prefilled from `hit.name` when it is Latin). It does not use a modal.
  - Each `added` company card gets a "הסר ממעקב" button with a `confirm()` prompt.
- `onSuccess` invalidates the `['companies']` and `['search']` query keys.
- Buttons are disabled when `mode !== 'live'`. The tooltip text depends on `liveAllowed` from `useMode()`.
- The remove button sits outside the card's `<Link>`, so clicking it doesn't navigate.

### D8. Schema rollout on the hosted database
`schema.sql` gains the table using `create table if not exists`. `PgStore._check_schema` is left as is (it checks `kv_cache`). Instead, the tracked-companies queries catch `UndefinedTable` like every other query (via `_run`) and raise `StorageNotInitialized` with the `db init` hint. Until the operator re-runs `db init`, the home page would fail with that error. So the deploy step comes before the code reaches Render (see Migration Plan).

*Alternative:* treat a missing table as "no added companies". Rejected: it hides a misconfiguration, and an add would then fail anyway.

## Risks / Trade-offs

- [The public hosted app with live mode on lets anyone add or remove runtime companies] → It is off by default (`ALLOW_LIVE=false`). The README runbook already says to turn live mode on only for a demo. Removing never deletes cached data, and YAML companies can't be removed.
- [A wrong `fr_company_id` is saved, since D5 doesn't check it] → It shows up as an empty or unexpected filing list. Remove it and add it again.
- [An extra store read on every ticker resolution] → One primary-key or small-table query, much cheaper than any provider call. It can be cached per request later.
- [Archive order with `deploy-render-supabase-storage`] → That change introduces the state store and the Postgres backend. Archive it first. This change's deltas don't touch its requirements.

## Migration Plan

1. Merge the code. Locally (fs backend) nothing needs migrating: the JSON file is created on the first add.
2. Before or right after the Render deploy, run `stock-analyzer db init` with the hosted `DATABASE_URL` from a developer machine. It is idempotent, and existing rows are kept.
3. Check `GET /api/companies` on the hosted API. It should return MLTM with `source: "registry"`.
4. Rollback: redeploy the previous image. The extra table is ignored by old code, so no down-migration is needed.
