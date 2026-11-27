## Context

Peers come from `services/peers.select_peers` (exact ISIC class, IL first, ordered by provider ID). Ratios come from `services/ratios.analyze`, which takes a ticker and builds cached financials into a canonical sheet, checks and ratio series. In `cached` mode, FRClient raises `NotCached` on a miss and never calls the provider.

## Decisions

**D1 Peer matching: DECIDED, curated list with exact-class fallback (user choice, 2026-11-26).** A tracked company may carry a curated `peers` list (provider IDs, each tagged with its market). If the list exists, the benchmark uses it, grouped into market cohorts, with no limit per cohort. If there is none, it falls back to the existing exact ISIC sub-industry match from `select_peers`, run per market cohort. There is no widening to the 3-digit group. Each cohort reports its source (`curated` or `sub_industry`). The curated list lives in `server/data/companies.yaml` (the version-controlled registry). Store-added companies use the fallback. This avoids a schema migration. MLTM is seeded with Accenture, Capgemini and Sopra Steria once their provider IDs are resolved (task 1.1). Options considered:
- A. Exact class only (current behaviour). Simple and auditable, but can return no peers or the wrong ones.
- B. Exact class, widening to the 3-digit ISIC group for any cohort with fewer than `min_peers` (default 3). Each cohort is tagged with the level used. Rejected: the user chose curated plus exact class only.
- C. A curated `peers` list per tracked ticker (for example MLTM: Accenture, Capgemini, Sopra Steria), with A or B as the fallback. The most relevant peers, but the list needs manual upkeep.

Inside a cohort, ranking stays by provider ID because it is deterministic. Ranking by size would need financials for every candidate, which costs credits, so it is out of scope.

**D2 Per-market cohorts.** A `markets` setting maps each cohort to its countries and limit: `IL`, `US`, and `EU = GB, FR, DE, NL, ES, IT`. Cohorts replace fill-the-remainder for the benchmark only. The `peer-financials` CLI keeps its current spec.

**D3 Ratios per peer.** Split `analyze` so it can take a provider company ID, which lets untracked peers be analyzed. The GET path uses cached mode only. A peer that raises `NotCached` is marked `financials_not_cached`, and an unsupported template is marked `template_not_supported`.

**D4 Comparability.** Ratios are dimensionless, so currency is reported but not converted. Medians use only peers on the target's template whose latest fiscal year is within ±1 of the target's. The count `n` is shown.

**D5 Live run.** `POST` requires live mode. It first counts the uncached peer financials and returns `estimated_credits` (40 each) without fetching. Only with `confirm=true` does it fetch, capped at `max_fetch` (default 5 = 200 credits) per run. Fetches go through FRClient, so the results land in `kv_cache`.

**D6 Directory pages.** Directory pages cost 1 credit each and are cached. If they are not stored, the GET returns `not_cached` (409), as the OSINT GET does.

## Risks

- MLTM's class and its cached peer pages were not verified during planning because the store was unreachable. Apply task 1.1 checks them before any code is written.
- The EU cohort may be empty for a narrow class. B or C mitigates this.
