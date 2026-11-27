# Proposal

## Why

The report screen (radar, score list, events, key metrics) is built to the JSON contract in
`docs/company-report-spec.md`, but it still loads hand-written MLTM fixtures because no server
produces the contract. Saved story runs already hold everything the contract needs: the
narrative judgement in `what_changed` and `story_vs_numbers`, plus the sheet values (`FIN:`),
ratios (`RATIO:`), changes (`CHG:`) and quoted numbers (`TXT:`) the story was written against.
El Al (ELAL) has a complete run, so it can be the first real report.

## What Changes

- New **rater** step: one LLM call reads a saved story run and scores five axes for each of the
  run's fiscal years. The axes are `stability`, `safety` (the opposite of risk), `revenue_quality`,
  `growth` and `profitability`. The story is what gets judged. Every score cites fact ids from the
  run as its evidence. A year the story says nothing about for an axis gets `null` and
  `insufficient_data`, never a guess.
- Verification of the rater output: every cited fact id exists in the run, scores are 1-10 or
  `null`, and labels stay within the contract's character limits. A failed check sends the
  errors back to the rater once, like the storyteller's retry.
- Assembly of the full `CompanyReport` from the run: company and report info, summary, years,
  axes with trends computed from consecutive scores, events taken from the story, and key
  metrics taken from `FIN:` and `RATIO:` facts. `sector_median` is always `null` for now.
- New endpoints: `GET /api/companies/{ticker}/report` and
  `GET /api/companies/{ticker}/report/axes/{axis_id}?year=`. They are built from the latest
  saved story run. Cached mode returns the report saved for that run. Live mode builds and saves
  it when it is missing.
- New CLI command `stock-analyzer report <TICKER> [--live]` that calls the same service.
- The web report page loads from the API for tickers that have a report, and keeps the MLTM and
  SPARSE fixtures as dev data.

Out of scope: sector medians and peer comparison, the `valuation` axis, SSE progress for the
report, and re-running the story.

## Capabilities

### New Capabilities
- `company-report`: scoring a saved story run into the five-axis profile, verifying the scores
  against the run's facts, and assembling the company report contract (axes, axis details,
  events, key metrics).

### Modified Capabilities
- `analyzer-api`: adds the report and axis-detail endpoints and their cached/live behaviour.
- `web-client`: the report page loads the report from the API instead of only from fixtures.

## Impact

- Server: new `stock_analyzer/report/` package (rater agent, verify, assemble), new prompt
  `prompts/report_rater.md`, a new service in `services/`, a new router, and a CLI command.
  It reuses `StoryRun`, `FactRegistry` and the LLM gateway. The built report is saved in a new
  `report` namespace of the key-value cache, keyed by story run id. That needs one small schema
  change: the namespace check constraint gains `report`.
- `server/openapi.json` and `web/src/api/schema.d.ts` are regenerated. `web/src/features/report/queries.ts`
  switches to the API.
- Cost: one main-role LLM call per (story run, prompt version). The FinancialFilings provider
  is not called.
