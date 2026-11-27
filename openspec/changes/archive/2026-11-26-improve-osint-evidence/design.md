# Design

## Context

See proposal.md for motivation and the delta specs for required behavior.

Current pipeline (`osint/agents.py: run_pipeline`): the orchestrator profiles the company with
`web_search` and briefs six specialists (its final output is free text and is discarded) → specialists
return `AreaReport`s → `verify_findings` keeps findings whose URL a search returned and whose date is in
the window → the synthesizer turns the kept findings into a `Scorecard` → `check_scorecard` enforces
citations and coverage. The search tool keeps up to 1500 characters of each result's excerpt in
`RunState.seen_urls`. Progress events and run guards (add-osint-web) wrap this pipeline.

Calibration on the stored ELAL result: the known duplicate pairs (fare cuts F16/F32, fines F27/F37 and
F28/F38, 737 MAX order F36/F44) score 63-71 on rapidfuzz `token_set_ratio`, while two *different* fines
(F27/F28) score 67. Text similarity cannot separate duplicates from distinct events.

## Goals / Non-Goals

**Goals:**
- Each kept claim is supported by its source; each event counts once; the scorecard says where the
  company is heading and what matters for its industry.
- Added cost stays small (cheap model, batched calls), and every step runs offline in tests.

**Non-Goals:**
- Fetching full pages to verify claims (the excerpt the run already holds is the evidence).
- Numeric scores or a deterministic label formula (labels stay model-made, now weighted by importance).
- Calibrating labels across companies, or a backtesting/evaluation set.

## Decisions

### D1. New pipeline order
```
orchestrator (output: CompanyProfile) -> specialists -> verify_findings (URL, window)
  -> check_claims (cheap model, batched)      drops "unsupported"
  -> merge_duplicates (exact pass + cheap-model grouping)
  -> trend_hints (code)
  -> synthesizer (profile + merged findings + hints) -> check_scorecard (extended)
```
Verification runs before merging so a merged finding's sources are all checked.

### D2. Structured company profile
The orchestrator gets `output_type=CompanyProfile` (industry, business_lines, controlling_shareholder or
null, competitors, regulator or null, key_drivers: 3-6 short phrases). It is stored in the result and
given to the synthesizer. If the orchestrator fails, the profile is null and the synthesizer names the key
drivers itself from the findings.
- *Alternative: a separate profiling agent.* Rejected: the orchestrator already profiles the company
  before briefing; making its output structured costs nothing extra.

### D3. Claim check with a cheap verifier agent
A `verifier` agent on `MODEL_CHEAP` (the model factory returns a cheap `OpenAIChatCompletionsModel` for the
`verifier` and `grouper` roles) gets batches of about 10 findings, each with its claim and the excerpt
for its URL, and returns `{id, verdict, reason}` per finding. Batches run concurrently. A finding with no
excerpt is `unverified` without a model call; a finding the verifier leaves out is `unverified`. The
prompt says to judge only from the excerpt and to mark claims whose numbers the analyst computed or
rounded as `partial`. The search tool keeps up to 3000 characters per excerpt (was 1500).
- *Alternative: let the main model self-check.* Rejected: same model, same blind spots, higher cost.

### D4. Merging duplicates
1. Exact pass in code: same normalized URL and `token_set_ratio >= 90` (near-identical wording).
2. One `grouper` call on `MODEL_CHEAP` with every remaining claim (id, area, date, claim) returns groups of
   ids that describe the same event. Code accepts only groups of existing ids, each id at most once.
The representative of a group is chosen by verdict (supported > partial > unverified), then confidence,
then the newer date, then the lower id. It keeps its claim and gains `also_sources` (url, title) and
`also_areas`. Findings are renumbered F1..Fn after merging; the result reports `merged`.
- *Alternative: fuzzy matching only.* Rejected by the calibration above.

### D5. Trend hints in code, trend decided by the synthesizer
For each area, code splits kept findings with a date into recent (last 12 months before the run date) and
older (the rest of the window), and counts positive minus negative signals in each. The hints go to the
synthesizer, which sets `trend` and `trend_reason` per area and overall. `check_scorecard` forces `unclear`
for areas with insufficient data.

### D6. Industry focus in the scorecard
`AreaAssessment` gains `importance` (high/medium/low for this industry) and the synthesizer is told to
weigh the overall label by it. `Scorecard` gains `key_drivers`: one entry per profile driver with status
(positive/negative/mixed/unknown), a Hebrew explanation and finding ids. `check_scorecard` drops unknown
ids and sets a driver with no valid ids to `unknown`. The synthesizer writes one driver per profile driver, in
Hebrew and in the profile's order; `check_scorecard` keeps the model's drivers as given and lists the
profile's drivers (all `unknown`) only when the model returned none. The first live ELAL run showed why:
matching Hebrew names against the English profile appended every profile driver again as an "unknown"
duplicate.

### D7. Strict agent outputs, tolerant stored results
Agent output models keep no defaults (the SDK sends strict schemas). Stored `ResearchResult`s from before
this change lack the new fields, so `ResearchResult` gets a before-validator that fills them (verdict
`unverified`, trend `unclear`, importance `medium`, empty drivers, null profile, merged 0). The API schema
and the web view treat them as optional.

### D8. Display
CLI text output: profile line, key drivers, importance and trend per area, verdict and "also reported by"
per source, merged and unsupported counts. API: the new fields on `ResearchResult`; regenerate
`server/openapi.json` and `web/src/api/schema.d.ts` (`npm run gen:api`). Web `OsintPage.tsx`: profile and
key-drivers section above the areas, importance and trend badges per area and overall, verdict badge and
other sources per finding; sections are left out when a field is missing.

### D9. Offline path
`FakeAgentModel` gains `verifier` (all supported) and `grouper` (no groups unless scripted) roles, and the
orchestrator fake returns a profile. Tests script the grouper to check merging.

### D10. Legal and regulation areas
Two areas are added to `AREAS` (`legal`, `regulation`) with their own specialists; `news` drops "legal and
regulatory actions" and `labor_government` drops regulation and policy change, so findings land in one
place. `israel_market.md` lists Israeli court and legal sources (court sites, the class-actions registry,
legal press, Hebrew search terms) and regulation sources (Knesset, gov.il, regulators' consultations). The
synthesizer is told to weigh material proceedings and near-final regulation and raise them among the top
risks. `OSINT_MAX_SEARCHES` goes from 40 to 52 (stored ELAL runs used all 40 with six areas). Stored
results with six areas still load; the web view only renders the areas a result has.

### D11. Hosted deployment
The server `Dockerfile` copies `data/companies.yaml` only, so `data/osint_blocklist.yaml` (read by
`osint/blocklist.py` on every run) was missing on Render. The image now copies it; `render.yaml` sets
`MODEL_OSINT`, `OSINT_MAX_SEARCHES` and `OSINT_WINDOW_MONTHS` as plain values (secrets stay `sync: false`).
A unit test parses the Dockerfile and blueprint so a missing OSINT file or setting fails CI. Live OSINT
runs on Render follow `ALLOW_LIVE` like every other live call. The lockfile (revision 5) was checked with
the image's uv 0.11 and reads fine.

### D12. SDK upgrade from main
While this change was in progress `main` moved to `openai>=3` and `openai-agents==0.26.0`. The OSINT code
(fake model, hooks, `preserve_raw_usage`) runs unchanged on 0.26; all OSINT tests pass after the merge.

## Risks / Trade-offs

- [Verifier too strict on short excerpts] → excerpts grow to 3000 characters; missing evidence gives
  `unverified` (kept, low confidence), not a drop. Only a clear contradiction or absence of the stated
  fact in the excerpt gives `unsupported`.
- [Grouper merges distinct events] → the prompt asks for the same event only; merged findings keep all
  sources visible, so a wrong merge is easy to spot.
- [Synthesizer ignores the hints] → the hints and trend reason are shown, and insufficient-data areas are
  forced to `unclear` in code.
- [Extra cost] → about 5 verifier calls plus one grouper call on the cheap model, roughly $0.01-0.05.
  Measured on the live ELAL run: $1.31 in total (first run $0.96), all 52 searches used, 6 findings dropped
  as unsupported, 4 duplicates merged.
- [Old stored results] → filled by the before-validator; covered by a test with the stored ELAL JSON shape.

## Migration Plan

Additive. No schema or config change; old stored results load with defaults. Roll back by reverting the
change; results stored with the new fields still load in the old code only if extra fields are ignored,
which pydantic does by default.
