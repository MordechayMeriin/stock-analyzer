# Proposal

## Why

The first live OSINT run on El Al (47 findings, every area WATCH, $0.96) showed that the research collects
plenty of sources but analyses them weakly. Claims are only checked to come from a searched URL, not that
the source says them. The same event is counted several times across areas, which inflates the evidence.
The scorecard is a single snapshot, although the run covers three years. And it treats all six areas as
equally important, while what decides stability differs by industry. The point of the tool is the
analysis: focus on what matters for the company's industry and say how the company stands and is moving.

## What Changes

- **Claims checked against their sources.** After the existing URL and window checks, a cheap model
  checks each finding's claim against the search excerpt the run already holds. Unsupported findings are
  dropped; partly supported and unverifiable ones are kept at low confidence. Each finding shows its
  verdict.
- **Duplicate findings merged.** Findings that describe the same event (also across areas) are merged
  into one, keeping the strongest version and listing the other sources. The scorecard sees each event
  once, and the result reports how many duplicates were merged.
- **Trend per area and overall.** Each area and the overall assessment get a direction (improving,
  stable, deteriorating, unclear), explained in Hebrew, using how recent the positive and negative
  findings are.
- **Industry-focused analysis.** The company profile the orchestrator builds becomes part of the result:
  industry, business lines and the key drivers of stability for that industry. Each area gets an
  importance for this industry (high, medium, low), the scorecard gets a "key drivers" section with the
  status of each driver and its findings, and the overall label weighs areas by their importance.
- **Two new research areas** (user requests during implementation): *legal proceedings* (court cases,
  class actions, investigations, enforcement, rulings) and *upcoming regulation* (bills, directives,
  reforms, licence, tariff and tax changes, with status and effective date). `news` and
  `labor_government` are narrowed so they do not overlap. The default search limit rises from 40 to 52 to
  make room (about +$0.10 per run).
- **Runs on Render.** The server image was missing the OSINT block-list, so OSINT would crash on the
  hosted API; the image now carries it, `render.yaml` sets the OSINT settings, and a test fails if a file
  OSINT needs is missing from the image.
- The CLI text output, the API result and the web OSINT view show the new fields: profile and key
  drivers, area importance and trend, verdict badges and merged sources.
- Added cost: one extra cheap-model pass per run (around $0.01-0.05) plus up to 12 more searches for the
  two new areas (about $0.10); about $1.2 per run in total.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `osint-research`: eight research areas instead of six (modified requirement), and new requirements for
  checking claims against sources, merging duplicate findings, trend per area and overall,
  industry-focused analysis (profile, key drivers, area importance), and the legal and regulation areas.
- `web-client`: new requirement for showing the profile, key drivers, importance, trend, verdicts and
  merged sources in the OSINT view.
- `deployment`: new requirement that OSINT runs on the hosted API (files in the image, settings in the
  blueprint).

## Impact

- **Code:** `server/stock_analyzer/osint/` (models, verify, agents, search, new `evidence.py`),
  `services/osint.py`, `prompts/osint/` (orchestrator, synthesizer, `israel_market.md`, new `verifier.md`
  and `grouper.md`), `config.py` (search limit 52), `cli.py` (text output), `server/openapi.json`
  (regenerated), `web/src/features/osint/OsintPage.tsx` and the API types.
- **Deployment:** `server/Dockerfile` (copies the block-list), `render.yaml` (OSINT settings), new
  `tests/unit/test_deploy_osint.py`.
- **Stored results:** new optional fields on stored OSINT results. Results stored before this change still
  load and display without them.
- **No change** to filing exclusion, cached/live behavior, progress events or run guards.
