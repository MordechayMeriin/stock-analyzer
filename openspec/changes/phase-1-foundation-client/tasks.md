# Tasks

## 1. Repository scaffold

- [x] 1.1 Create the root layout (`server/`, `web/`, `.gitignore` excluding `server/data/*` except `companies.yaml`, logs, runs, `.env`, `node_modules`, `dist`) and verify `git status` shows no data or secret files after a fetch
- [x] 1.2 Create `server/pyproject.toml` (Python 3.11+, deps from plan.md §0 minus chromadb/sentence-transformers, plus fastapi, uvicorn, sse-starlette) and the `stock_analyzer` package skeleton; verify `uv sync` succeeds and an empty `pytest` run passes
- [x] 1.3 Add `config.py`, which reads every setting from env with defaults (`FR_API_KEY`, `OPENROUTER_API_KEY`, `DATA_DIR`, `ALLOW_LIVE`, `CORS_ORIGINS`, `MODEL_MAIN`, `MODEL_CHEAP`, `PLAYGROUND_MAX_TOKENS`, parser thresholds), plus `.env.example`; verify a unit test that defaults load with no env set and that secrets are never in `repr()`
- [x] 1.4 Scaffold `web/` with Vite + React + TypeScript, Tailwind, shadcn/ui, TanStack Query, React Router, `<html dir="rtl" lang="he">` and a Hebrew font; verify `npm run build` and `npm run lint` pass

## 2. LLM gateway

- [x] 2.1 Implement `llm.py` `complete_json` (OpenRouter through the OpenAI-compatible client, JSON-schema output, pydantic validation, one repair retry carrying the error); verify unit tests for valid output, a successful repair, and a failed repair raising with the raw output (HTTP mocked with respx)
- [x] 2.2 Add the disk cache keyed by model, prompts, schema and params, and the JSONL cost/latency log under `DATA_DIR/logs/llm.jsonl`; verify a test showing that a second identical call is a cache hit with cost 0 and both calls are logged
- [x] 2.3 Implement `stream_text` yielding `delta` events and a final usage/cost event; verify a test against a mocked streaming response
- [x] 2.4 Implement `FakeLLM` (scripted or schema-derived responses, streaming supported) behind the same interface; verify the full suite passes with the network disabled and no API key

## 3. Filings client

- [ ] 3.1 Check paths and fields against the provider's `/api/schema/` (companies, filings, markdown paging headers, financials endpoint, `include=revisions`, usage) and record the findings in `server/docs/fr_api.md`; verify the doc lists each endpoint used, with its confirmed parameters
- [ ] 3.2 Implement `fr_client.py` with the `X-API-Key` header, retries with exponential backoff that honor `Retry-After` on 429/5xx, immediate failure on other 4xx, a permanent disk cache with `refresh`, a cached-only mode raising `NotCached`, and a credit log in `DATA_DIR/logs/fr.jsonl`; verify respx tests for each of these behaviors and that the API key never appears in logs
- [ ] 3.3 Implement `search_companies`, `list_filings`, `get_markdown` (follow the next offset; assert the total equals `X-Total-Chars`; save `raw/{ticker}/{fy}.md` + `.meta.json`), `get_financials` and `usage`; verify respx tests, including a multi-page fetch and the truncation failure
- [ ] 3.4 Add `data/companies.yaml` (MLTM) and `select.py` implementing the report-selection rule; verify tests reproducing Malam FY2025 → 32935334, FY2024 → 63741657, and a loud failure when there is no candidate
- [ ] 3.5 Add the `cli.py` commands `fetch TICKER FY... [--refresh]` and `usage`; run a live fetch of Malam FY2024/FY2025 plus financials once; verify the raw files exist, the lengths match their metadata, and the credits used are logged
- [ ] 3.6 Save trimmed fixture slices (TOC, risk section, legal section, one table, auditor's report, pages in style A and style B, plus a saved financials JSON) to `server/tests/fixtures/`; verify fixtures are under a size budget and full documents are not committed

## 4. Report parsing

- [ ] 4.1 Implement the shared `ingest/normalize.py` (bidi controls, `**`/`<u>`/`<br>`, geresh/gershayim unification, entities, whitespace); verify table-driven unit tests, including `ש״ח` ≡ `ש"ח`
- [ ] 4.2 Implement page-style detection and page assignment in `parse_md.py` (style A markers, style B `---` excluding table dividers, printed-page footers, the offset consistency check); verify tests on both fixtures, including the Malam FY2024 offset of 2
- [ ] 4.3 Implement stripping of footers, picture text and repeated lines, plus paragraph splitting into the `Paragraph` model with stable `pid`s and one paragraph per table; verify tests for stable ids across runs, a repeated header removed, and a table kept as one paragraph
- [ ] 4.4 Implement chapter detection in `structure.py`, ignoring TOC matches, with once-per-chapter sanity; verify a test on Malam FY2025 showing all five chapters found once
- [ ] 4.5 Implement TOC parsing and title-anchored business sections (`token_set_ratio` threshold from config); verify a test where the TOC says 25 and the body says 22 and the section is still found by title, plus a warning when fewer than 10 sections are found
- [ ] 4.6 Implement subsection regexes for all six numbering forms, directors'-report lettered headings, and splitting financial statements into the auditor's report, the statements and the `ביאור N` notes; verify one test per numbering form and a notes test
- [ ] 4.7 Add the `structure TICKER FY` CLI command, which prints the tree with page ranges and a coverage summary; run it on cached Malam 2024 and 2025 and verify the tree against the Markdown by spot-checking 5 sections; record any discrepancies as fixtures plus tests

## 5. Financial data

- [ ] 5.1 Implement `fin/normalize.py` → `FinValue` (exact Decimal from raw value × scale, statement, currency, `available_at`, source filing) with a currency-mismatch error and an `as_of` filter; verify tests for the scaled value (4,138,004 thousands → 4138004000), the mismatch error, and the late-availability trap for Malam FY2023
- [ ] 5.2 Add the `fin-raw TICKER` CLI command, which prints values grouped by statement and year; verify it runs on cached Malam and shows FY2025 revenue

## 6. Analyzer API

- [ ] 6.1 Implement the `services/` layer (companies, filings with the selected flag and cached status, report structure, node paragraphs, page paragraphs with citation URLs, financials, usage including LLM spend) and switch the CLI commands to call it; verify service unit tests on fixtures
- [ ] 6.2 Create the FastAPI app with the error model (`code`, `message`, mapped statuses), CORS from `CORS_ORIGINS`, a `mode` request parameter honoring `ALLOW_LIVE`, and a `/health` endpoint reporting credential presence; verify TestClient tests for 404 `company_not_found`, a `not_cached` error, live refused when disabled, and health flags
- [ ] 6.3 Add routers for companies, filings, report structure, node and page paragraphs, financials (decimals as strings) and usage; verify TestClient tests per endpoint plus a parity test checking that CLI and API structure output for MLTM 2025 match
- [ ] 6.4 Add the SSE playground endpoint (node or page selection → labeled paragraphs + question → `MODEL_MAIN` via `stream_text`, using `prompts/playground.md`), with a size check against `PLAYGROUND_MAX_TOKENS`; verify FakeLLM tests for event order (`delta`… `done` carrying cost and paragraph ids) and rejection of an oversized selection
- [ ] 6.5 Export `openapi.json` with a script and document running the API in `server/README.md`; verify that following the README starts the server and `/docs` lists every endpoint

## 7. Web client

- [ ] 7.1 Generate TS types from `openapi.json` with `openapi-typescript`, and build the typed API client (base URL from runtime `/config.js`, falling back to `VITE_API_BASE_URL`) and an SSE helper using fetch, a stream reader and an AbortController; verify a staleness check script fails when the types are outdated
- [ ] 7.2 Build the app shell: RTL layout, navigation, company context, the cached/live mode control (locked when the server disallows live), and shared loading, empty and error components with retry; verify in the browser that the shell renders RTL and the mode control reflects `/health`
- [ ] 7.3 Build the company and filing browser (tracked list + search, filings by year with the selected report and cached badges, credit usage); verify in the browser that selecting Malam shows FY2024/FY2025 correctly
- [ ] 7.4 Build the report reader (structure tree, node paragraphs with printed page markers, links to `document_url#page=N`, deep-link routes `/:ticker/:fy/report/:nodeId`); verify in the browser that the risk section opens through a deep link and its page links target the right PDF pages, and that mixed Hebrew/Latin text renders correctly
- [ ] 7.5 Build the financials view (statement-grouped table, one column per year, currency-formatted decimals, currency label); verify in the browser on Malam
- [ ] 7.6 Build the LLM playground (pick a node or pages, enter a question, stream the answer, cancel keeping the partial answer, cost and source-paragraph links when done); verify in the browser against the FakeLLM-backed server and once live
- [ ] 7.7 Document dev setup and configuration in `web/README.md`; verify that following it from a clean checkout runs the client against a local server

## 8. Deployment

- [ ] 8.1 Write `server/Dockerfile` (slim Python, uv, uvicorn, `/data` volume, non-root user, no secrets); verify `docker build` succeeds, the container serves `/health`, and inspecting the image shows no `.env` or data
- [ ] 8.2 Write `web/Dockerfile` (Node build → nginx serving `dist/`, with an entrypoint writing `/config.js` from `API_BASE_URL`); verify one image built once works against two different API URLs
- [ ] 8.3 Write `docker-compose.yml` (server + web, `.env`, `./server/data` mounted, `ALLOW_LIVE` defaulting to false) and a root `README.md` covering the one-command local run and separate deployment of each part; verify that `docker compose up` serves the client and it loads cached Malam data
- [ ] 8.4 Add CI with path filters (server: lint + pytest offline; web: lint + build + OpenAPI type-staleness check); verify both jobs pass and each triggers only on its own paths

## 9. End-to-end check

- [ ] 9.1 Starting from a clean checkout with cached Malam data only, run the stack in cached mode and walk through each view: browse → read the risk section through page links → financials → a playground question with FakeLLM. Verify zero provider calls in `fr.jsonl` during the walkthrough
- [ ] 9.2 Run one live playground question and one `--refresh` fetch against the real services; verify that the cost and credits appear in the usage panel and the logs

## Workflow follow-up

- Archive this change once Phase 1 is reviewed, then propose the Phase 2 (evals) change from the roadmap in proposal.md.
