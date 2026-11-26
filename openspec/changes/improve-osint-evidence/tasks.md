# Tasks

## 1. Models and compatibility

- [x] 1.1 Add `CompanyProfile`, verdict, trend, importance and key-driver models to `osint/models.py` (agent outputs without defaults); extend `KeptFinding` (verdict, also_sources, also_areas), `AreaAssessment` (importance, trend, trend_reason), `Scorecard` (overall_trend, overall_trend_reason, key_drivers) and `ResearchResult` (profile, merged, unsupported count); verify agent output models still mark every field required in a unit test
- [x] 1.2 Add the before-validator that fills missing fields on stored results; verify the stored ELAL result JSON from before the change loads with the documented defaults in a unit test

## 2. Claim check

- [ ] 2.1 Raise the stored search excerpt to 3000 characters in `osint/search.py`; verify with the existing search tests updated
- [ ] 2.2 Add the verifier prompt (`prompts/osint/verifier.md`) and `check_claims` (batches of about 10, concurrent, cheap-model `verifier` role, missing excerpt or missing verdict gives `unverified`, partial and unverified forced to low confidence, unsupported dropped and counted); verify with fake-model tests for each verdict and for a batch the verifier leaves incomplete
- [ ] 2.3 Return a cheap model for the `verifier` and `grouper` roles in `live_model_factory` and log the calls as `osint-agent:osint_verifier` / `osint_grouper`; verify the usage records appear after a fake run

## 3. Duplicate merging

- [ ] 3.1 Implement the exact pass (same normalized URL and `token_set_ratio >= 90`) and representative choice (verdict, confidence, newer date, lower id) with `also_sources` / `also_areas` and renumbering; verify with unit tests, including two different events from the same URL staying separate
- [ ] 3.2 Add the grouper prompt (`prompts/osint/grouper.md`) and the grouping call with group validation (existing ids only, each id once, groups of two or more); verify with a scripted grouper merging the ELAL-style fine duplicates and rejecting an invalid group

## 4. Trend and industry focus

- [ ] 4.1 Make the orchestrator return `CompanyProfile` (output type and prompt) and store it on the run; fall back to null when the orchestrator fails; verify with fake-model tests for both paths
- [ ] 4.2 Compute trend hints per area (recent 12 months vs older, net signals) and pass profile, merged findings and hints to the synthesizer; update the synthesizer prompt for importance weighting, key drivers and trend; verify the synthesizer input in a fake-model test
- [ ] 4.3 Extend `check_scorecard`: insufficient-data areas get trend `unclear`, unknown ids are dropped from key drivers, drivers without valid ids become `unknown`; verify with unit tests
- [ ] 4.4 Wire the new steps into `run_pipeline` in the order of design D1 (keeping progress events), set `merged` and the unsupported count on the result; verify a full offline run through `services.osint.run_research` returns profile, key drivers, trends and verdicts

## 5. Display

- [ ] 5.1 Show profile, key drivers, importance, trend, verdicts, other sources and merged/unsupported counts in the CLI text output; verify with the CliRunner tests in fake mode
- [ ] 5.2 Regenerate `server/openapi.json` and `web/src/api/schema.d.ts`; verify the API tests pass and the OSINT endpoints return the new fields in fake mode
- [ ] 5.3 Update `web/src/features/osint/OsintPage.tsx`: profile and key-drivers section, importance and trend per area and overall, verdict badge and other sources per finding, sections left out for older results; verify `npm run build` and `npm run lint` pass and check the page in the local preview with the stored ELAL result and a fake-mode result
- [ ] 5.4 Update the OSINT section of `server/README.md`; verify the documented commands run as written in fake mode

## 6. Integration check

- [ ] 6.1 Run the server suite (`PYTHONUTF8=1`) and `ruff check`; verify both pass
- [ ] 6.2 With the user's go-ahead on cost, run ELAL live once and compare with the first run: duplicates merged, unsupported count, trends and key drivers present, cost within about $0.05 of the first run plus the extra pass

## Workflow follow-up

- Archive `add-osint-web` (merged, not archived) before archiving this change, so the web-client deltas sync in order.
- Archive this change after review with `/opsx:archive`.
