# Design

## Context

`add-osint-research` already added `GET`/`POST /api/companies/{ticker}/osint`, with a blocking `POST` that
returns JSON after the run, and a page that runs research on one click. This design replaces the run path and
the page. `services.osint.run_research(ctx, ticker, months)` is synchronous: it resolves
the company, and in live mode (or `LLM_FAKE`) runs `asyncio.run(run_pipeline(...))`, which takes several
minutes and about $1 of OpenRouter credit, then stores the result in the `llm` cache under
`osint:{TICKER}:{months}m:latest`. `cached_result(ctx, ticker, months)` reads that key. The pipeline has no
progress reporting. `NoFindings` is already an `AnalyzerError` mapped to 422 `osint_no_findings`.

The API already has the patterns this change follows: `?mode=` via `CtxDep`; refusals as `AnalyzerError`
subclasses mapped in `api/errors.py`; the streaming playground (`POST` + `sse_starlette`, `delta`/`done`/
`error` events, with all validation done before the stream starts). The web client has a `postSse` helper
that understands only `delta`/`done`/`error`, a mode context (`useMode`) that forces `cached` when the
server disallows live calls, and lazy-loaded per-company routes (`/:ticker/ratios`).

## Goals / Non-Goals

**Goals:**
- Reading a stored result is free and instant in both modes.
- A live run gives feedback during its minutes-long run and cannot be started twice for the same ticker
  and window at once.

**Non-Goals:**
- A durable job queue or resuming a run after a server restart.
- Cancelling a run once it has started (see Risks).

## Decisions

**D1. `GET` reads the cache directly, never `run_research`.** `run_research` in live mode always searches
afresh, so the GET handler resolves the company (for `company_not_found`) and calls `cached_result`; with
nothing stored it raises `NotCached`. Alternative: call `run_research` with a cached-mode context — rejected
because under `LLM_FAKE` it would run the fake pipeline, and its `live_disabled` message is about live runs.

**D2. Live run as an SSE stream on `POST /api/companies/{ticker}/osint`.** Same transport as the playground,
so the client reuses `postSse`. The handler validates before streaming: `months >= 1`, company tracked,
`ctx.mode == "live"` else `LiveModeRequired`, `settings.allow_live` (unless `llm_fake`) else
`LiveModeDisabled`, OpenRouter key present (unless fake) else `MissingCredential`, and acquires the run
lock. Alternatives: a background job with polling endpoints — more state (job ids, a jobs table or memory
map, expiry) for a single-user tool; a blocking POST — no progress for minutes and proxy timeouts.

**D3. The run executes in a worker thread; progress crosses via a queue.** `run_research` calls
`asyncio.run`, which cannot run inside the server's event loop, so the stream generator (a sync generator,
as in the playground, which Starlette iterates in a thread pool) starts the run in a
`threading.Thread`, and drains a `queue.Queue` of progress events, yielding `progress` events until the
thread posts its result or exception. A ping every 15 s keeps proxies from closing the idle stream.

**D4. Progress callback in `RunState`.** `RunState` gains `on_progress: Callable[[OsintProgress], None] |
None = None`; `run_research` takes an optional `on_progress` and passes it in. Calls are made at:
orchestrator start, each `web_search` (after counting), each area report collected (`area_done`), fallback
specialist start (`area_start`), and before synthesis. `OsintProgress` is a small pydantic model
(`step`, `area`, `searches_used`, `search_limit`). Exceptions raised by the callback are swallowed so a
broken stream never fails a paid run. The CLI passes none and is unchanged.

**D5. One run per ticker and window per server process.** A module-level `set` guarded by a
`threading.Lock` holds `(TICKER, months)`; a second request gets `ResearchInProgress`
(`research_in_progress`, 409). The key is released in the worker thread's `finally`, not in the
generator, so a client disconnect does not free the slot while the run continues.

**D6. Client disconnect does not stop the run.** The worker keeps running and stores its result; the
analyst sees it on the next GET. Stopping mid-run would waste the credit already spent and the SDK offers no
clean cancellation of in-flight tool calls.

**D7. Error mapping.** `NoFindings` moves to `stock_analyzer.errors` next to the other domain errors, keeping
its 422 `osint_no_findings` (only seen in-stream now); the CLI's import from `osint.agents` keeps working. `research_in_progress` → 409. In-stream
failures use `to_error`, like the playground.

**D8. Schemas.** `ResearchResult` and its nested models are pydantic already and become the GET
`response_model` and the `done` payload, so `openapi.json` describes them for `openapi-typescript`. An
`OsintEvents` documentation model lists `progress`/`done`/`error` payloads, as `PlaygroundEvents` does.
The POST body is `OsintRunIn {months: int | None}` (1-120) and mode stays a query parameter, like the
other company endpoints; the window moves out of the POST query (breaking only for the old page, replaced here).

**D9. Web.** `postSse` gets an optional `onEvent(event, payload)` for event names other than
`delta`/`done`/`error`, leaving the playground untouched. New lazy route `/:ticker/osint`
(`features/osint/OsintPage.tsx`) with a window select (12/24/36/60 months), using React Query for the GET (`not_cached` → empty state, not error).
Labels map to Hebrew and colour badges (stable green, watch amber, fragile red, insufficient grey); area
names come from the result's Hebrew `AREA_INFO` mirror in the client (the API returns area ids). Finding
ids (`F1`…) are rendered as numbers with anchors (`#source-F3`); risk/strength citations link to them.
The run button opens an inline confirmation panel (no new dialog dependency) with the cost warning; on
`done` the query cache is updated with the new result. The link is added to the company page next to
financials and ratios, with `data-testid` hooks for the browser checks.

## Risks / Trade-offs

- [The server restarts mid-run] → The run and its spend are lost; the previous stored result remains. Acceptable for a single-user tool.
- [Run lock is per process] → Several server workers could run duplicates. The app runs one worker (Render, local uvicorn); noted in the endpoint description.
- [Disconnected client keeps spending] → By design (D6); the cost warning says a started run cannot be stopped.
- [Thread per live run] → At most one per ticker/window and runs are rare; no pool needed.

## Migration Plan

No data migration: results keep their existing cache keys. Rollback is reverting to the blocking endpoint and the earlier page.
