# Proposal

## Why

The analyzer only looks at a company through its official annual and quarterly filings, and a teammate is
already building the filing analysis. How stable a company is also shows up in sources outside the filings:
news, credit ratings, analyst forecasts, bond and share prices, labor disputes, competition and geopolitics.
This change adds an open-source intelligence (OSINT) research run that collects and weighs those sources,
starting with El Al (ELAL), and never touches the filings, so the two analyses stay independent.

## What Changes

- Works for any tracked company, with Israeli market expertise: the run first profiles the company's
  industry, then researches each area with that industry's indicators and Israeli sources (TASE, local
  rating agencies, Israeli press and regulators). El Al is the first company it is used on.
- New OSINT research run for one tracked company: an orchestrating agent sends specialist agents to search
  the web, each returning cited findings for its area, and a final step turns the findings into a stability
  scorecard.
- Specialist areas: news and events; market signals (share price, TASE bond yields and spreads); credit
  ratings and analyst forecasts; operations and demand (passenger traffic, fleet); labor and government;
  competition, macro and geopolitics.
- Scorecard: one of three labels per area and overall (stable / watch / fragile, no numeric score), top
  three risks and strengths, every claim linked to a source URL and publish date. Summary in Hebrew.
  Real-time: every run searches live and describes the company today, with a default window of the
  past three years to show the trend.
- Strict filing exclusion: only the official filings are off limits. A block-list of the filing systems
  (Maya, Magna) and the filings provider is applied to every search and again to every result, and agents
  are told not to use annual or quarterly report documents found elsewhere. Everything else is open,
  including the company's investor-relations site and market-data sites. The run never reads the FinancialFilings
  provider or the stored reports and financials. News that only repeats filed numbers is kept but labelled
  as derived from a filing.
- Every finding must cite a URL that a search in the same run actually returned. Findings citing anything
  else are dropped.
- New CLI command `stock-analyzer osint <TICKER>`. Every run searches afresh; the latest result is stored and served when live calls are off; usage (tokens and
  search cost) is logged like other LLM calls.
- New model setting `MODEL_OSINT` (initially `openai/gpt-6.1-sol` on OpenRouter) and limits on searches per
  run.
- New dependency: the OpenAI Agents SDK, pinned to `openai-agents==0.20.0`, the last release compatible with
  the server's `openai<3` pin.
- Out of scope: an API endpoint and a web page for OSINT results (a later change), scheduled re-runs, and
  any use of filing data.

## Capabilities

### New Capabilities
- `osint-research`: OSINT stability research for a tracked company: filing-free web search, specialist
  findings with citations, the stability scorecard, caching, cost limits and the CLI command.

### Modified Capabilities
- `llm-gateway`: model roles grow from two (main, cheap) to three, adding an `osint` role configured by
  `MODEL_OSINT`.

## Impact

- **Code:** new `server/stock_analyzer/osint/` package (agents, search tool, block-list, scorecard model);
  `config.py` (new settings); `cli.py` (new command); `.env.example`.
- **Data:** new `server/data/osint_blocklist.yaml`. Cache entries and usage records reuse the existing
  `llm` namespace and source, so the database schema does not change.
- **Dependencies:** `openai-agents==0.20.0` in `server/pyproject.toml` and `uv.lock`.
- **Cost:** each run makes OpenRouter calls for the agents plus Exa web searches (about $0.007 per search),
  bounded by the per-run search limit. Runs are refused when live calls are disabled (`ALLOW_LIVE=false`)
  unless a cached result exists.
- **No effect** on filing fetches, parsing, ratios, the API or the web client.
