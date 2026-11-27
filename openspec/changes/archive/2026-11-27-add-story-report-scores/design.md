# Design

## Context

See proposal.md (Why). A saved `StoryRun` holds the Hebrew story (`story.what_it_does`,
`what_changed`, `story_vs_numbers` with `consistent`/`unexplained` labels), the rendered text,
the full fact registry (`facts`: `FIN:`, `RATIO:`, `CHG:`, `TXT:`, `DER:` ids with values and
currency), citations and the business profile. Agents are built with the Agents SDK through
`make_model(role, purpose)`, which caches every turn in the store's `llm` namespace and logs
usage. The storyteller's output is checked by `story/verify.py`, and errors go back for one
retry. The web contract lives in `web/src/features/report/types.ts` and
`company-report.schema.json`.

## Goals / Non-Goals

**Goals:**
- One rater LLM call per story run produces every judgement in the report. All other parts of
  the report are assembled deterministically from the run.
- The report is reproducible from (story run, saved report). It is never recomputed from
  current provider data.

**Non-Goals:**
- No formula that turns ratios into scores. Ratios are evidence the rater cites, not inputs
  to a band table.
- No streaming progress: the report endpoint is a plain request, and the live build is one
  LLM call.

## Decisions

### D1. The rater reads the story, not just the numbers
The rater's input is:
- the rendered story text, with fact values filled in;
- the findings with their labels;
- the profile;
- a facts table (id, name, years, rendered value), the same `facts_table` the storyteller sees.

The prompt (`prompts/report_rater.md`) defines each axis in story terms:
- stability: are the results repeatable, or driven by one-offs and market anomalies;
- safety: balance-sheet and liquidity risk, plus regulatory and legal threats;
- revenue_quality: where revenue comes from, how durable it is, and cash conversion;
- growth and profitability: the direction and level the story describes.

The prompt also tells the rater to use `null` when the story gives no basis.
*Alternative:* ratio bands with the story adjusting by ±1. Rejected because the user wants the
story to drive the scores.

### D2. Structured output with evidence ids
The output type is a Pydantic model:
- per axis, a list of `{fiscal_year, value: int | None, driver_label, driver_tone, evidence: [fact_id]}`;
- per (axis, year) with a score, a detail `{headline, factors: [{label, fact_id, tone}], text}`;
- `summary` (at most 160 characters);
- `events: [{date, date_precision, type, title, summary, importance, tone}]`.

Factors carry a `fact_id`, not a display string. The assembler fills `display` from the
registry's rendered value, so the model can never invent a number (this is the spec's
"factor values come from facts" requirement).

### D3. Verification reuses the registry
`report/verify.py` builds a `FactRegistry(run.facts)` and checks:
- every evidence and factor id exists in it;
- each value is in 1..10 or `None`;
- every axis × year is present;
- labels are within their character limits;
- each event type is in the contract's enum.

On errors, the agent runs again once, with the errors appended to its input. This is the same
pattern as the storyteller loop in `pipeline._build`. If it fails again, the request raises and
nothing is saved.

### D4. Deterministic assembly
`report/assemble.py` builds `CompanyReport` from the run, the tracked company and the verified
rater output:
- trends: delta of consecutive non-null scores; tone from the sign;
- axis `status`: `insufficient_data` if any of its scores is null;
- `sector_median`: `null`;
- `report` info: taken from the latest-year filing in `run.filing_ids` and the stored report
  metadata;
- `key_metrics`: revenue, operating_margin, net_income_consolidated and cfo, from the
  `FIN:`/`RATIO:` facts, with values as decimal strings;
- `detail_url`: `/api/companies/{T}/report/axes/{id}`.

The server's Pydantic models mirror `types.ts`, so the OpenAPI schema can replace the
hand-written TS types (the TODO in `types.ts`).

### D5. Storage: `report` cache namespace keyed by run id
The `kv_cache` namespace check gains `report` (and so does the `Namespace` literal). The key is
`{TICKER}:{run_id}`. This needs no new table, and both backends support it already.
*Alternative:* replaying the `llm` turn cache in cached mode. Rejected because the gateway has
no cache-only mode, and a miss would pay for a live call.

### D6. Model role
The rater uses the `main` role (it makes the judgement), with purpose `report.rater`.

## Risks / Trade-offs

- [Scores vary between runs and models] → A report is saved per run and never regenerated
  silently. The prompt hash is stored with the report.
- [2023 has thin narrative] → `null` with `insufficient_data` is allowed and shown as a hollow
  point. The prompt tells the rater not to guess.
- [The schema constraint change on hosted Supabase] → One `alter table ... drop/add constraint`
  in `schema.sql`, applied with the existing explicit schema setup.

## Migration Plan

1. Apply the updated `schema.sql` constraint.
2. Deploy the server.
3. Run `stock-analyzer report ELAL --live` once.

Rollback: remove the route. The extra namespace rows are harmless.
