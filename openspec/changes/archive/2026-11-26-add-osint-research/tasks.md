# Tasks

## 1. Dependency and configuration

- [x] 1.1 Add `openai-agents==0.20.0` to `server/pyproject.toml`, run `uv lock` and `uv sync`, and verify `uv run python -c "import agents"` succeeds with `openai` still below 3
- [x] 1.2 Add `model_osint`, `osint_max_searches`, `osint_search_results`, `osint_max_turns` and `osint_window_months` to `Settings` with env parsing (`MODEL_OSINT`, `OSINT_*`), and resolve role `osint` in `model_for`; verify with new cases in `tests/unit/test_config.py`
- [x] 1.3 Document the new settings in `.env.example` with `MODEL_OSINT=openai/gpt-6.1-sol`, add `MODEL_OSINT` to the local `.env`, and verify `Settings.from_env()` reads it

## 2. Block-list and search tool

- [x] 2.1 Create `server/data/osint_blocklist.yaml` (the official filing systems only; the IR site and market-data sites stay open) and a loader with a URL matcher supporting wildcards and path prefixes; verify with unit tests for domain, subdomain, wildcard and path matches
- [x] 2.2 Implement the `osint` package skeleton (`stock_analyzer/osint/`) with the `Finding`, `AreaReport` and `Scorecard` models and the per-run `RunState`; verify the models validate sample JSON in a unit test
- [x] 2.3 Implement the `web_search` tool: one OpenRouter call on the cheap model with the Exa web plugin and `exclude_domains`, parse `url_citation` annotations, drop blocked URLs, record returned URLs and the search count in `RunState`, refuse with a readable error past `OSINT_MAX_SEARCHES`; verify with respx tests for the request body, block-list filtering and the limit
- [x] 2.4 Log each search to the usage log (source `llm`, purpose `osint-search`, cost from the response); verify with a test that reads the record back from a file store

## 3. Agents and verification

- [x] 3.1 Write prompts for the six specialists, the orchestrator and the synthesizer under `server/prompts/osint/` (Hebrew and English search, window, filing-derived labelling, cite only searched URLs); verify each prompt file loads in a unit test
- [x] 3.2 Build the agents on `OpenAIChatCompletionsModel` with an OpenRouter `AsyncOpenAI` client and tracing disabled, specialists exposed to the orchestrator with `as_tool`; verify with a fake-model test that the orchestrator can call every specialist
- [x] 3.3 Implement finding verification (block-list, URL seen in this run, publish date inside the window) with dropped counts by reason; verify with unit tests for each drop reason
- [x] 3.4 Implement the scorecard checks: each risk, strength and area must cite kept finding ids, areas with no findings become `insufficient_data`, labels limited to stable/watch/fragile; verify with unit tests
- [x] 3.5 Add `RunHooks` usage logging for agent model calls (purpose `osint-agent:{name}`); verify records appear after a fake run
- [x] 3.6 Add a test that the `osint` package imports nothing from `ingest`, `fin`, or the report, filing and financials services, and makes no filings-provider call during a run

## 4. Run service, cache and live switch

- [x] 4.1 Implement `run_research(ctx, ticker, months)`: reject untracked tickers; in live mode always run afresh and store the result as the latest under `osint:{ticker}:{months}m:latest` in the `llm` namespace; when live calls are off serve the latest stored result or refuse; verify with tests for each path
- [x] 4.2 Implement the `LLM_FAKE` path with a scripted fake SDK model and fixture search results; verify a full offline run returns a scorecard with all six areas and no network access (respx with no routes)

## 5. CLI

- [x] 5.1 Add `stock-analyzer osint TICKER [--months] [--json] [--mode]` printing labels, risks, strengths, sources, search count, dropped counts and cost; verify with a CliRunner test in fake mode for both text and JSON output
- [x] 5.2 Document the command and its cost in `server/README.md`; verify the documented command runs as written in fake mode

## 6. Integration check

- [x] 6.1 Run `uv run pytest` and `uv run ruff check` in `server/` and verify both pass
- [x] 6.2 With the user's go-ahead on cost, run `stock-analyzer osint ELAL` live once, and verify the scorecard cites only non-filing URLs and the usage log shows the run's searches and agent calls

## 7. Any company, Israeli market focus

- [x] 7.1 Make the six area descriptions sector-neutral and add `prompts/osint/israel_market.md` (Israeli sources, market traits, sector guide) to every agent's prompt; verify a test finds no company or industry wording in the generic prompts and the guide covers the main sectors
- [x] 7.2 Give the orchestrator `web_search` to profile the company (industry, controller, competitors, regulator, bonds) before briefing specialists; verify a test sees `web_search` among the orchestrator's tools
- [x] 7.3 Verify an offline run for another tracked company (MLTM) produces a full scorecard with no extra configuration

## Workflow follow-up

- Archive the change after review with `/opsx:archive`.
- Plan the follow-up change for an API endpoint and a web page for OSINT results.
