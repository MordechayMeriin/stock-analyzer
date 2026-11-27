## Why

Users ask how a company compares with its industry in Israel, the US and Europe. The `peer-financials` CLI (PR #12) finds peers and prints their raw statements, but there is no API, no web view, and no side-by-side ratios or medians.

## Which parameter decides who counts as a peer (verified in code)

- **One field only:** the target's ISIC Rev. 5 class from the FinancialFilings company profile, `sub_industry.code` (`CompanyProfile.sub_industry_code`). `FRClient.list_peer_candidates` queries `/companies/?countries=..&sub_industry=<code>&listing_status=LISTED&view=full`. `services/peers.eligible_peers` then keeps rows with the same code, a requested country and `LISTED` status.
- **Order:** Israel (`IL`) first, then `--peer-country` markets fill the remaining places up to `--limit` (default 5). Ties are broken by **ascending provider ID**, not by size or similarity. A missing code returns `missing_sub_industry`.
- **MLTM's actual code:** **not verified yet.** While this was written, the Supabase connector refused the read (permission denied) and the database was unreachable from this machine. Task 1.1 reads it from the stored profile, or with one metadata call (1 credit) if it is not stored.
- **Risk:** an exact 4-digit class can be too narrow or too broad. Malam-Team covers IT services, outsourcing and infrastructure. If its class is 6201 (computer programming), Accenture or Capgemini may sit in another class (for example 6202 consulting). In a large market such as the US, "lowest provider ID first" picks arbitrary issuers rather than the obvious comparables. The current fill-the-remainder rule also means that five Israeli matches leave no room for US or EU peers.

## What Changes

- Run the existing ratio engine for each peer from cached financials only, using each peer's own statement template (industrial/bank/insurer). Ratios are unit-free, so currencies are reported but not converted. Peers on a template other than the target's are listed but excluded from medians.
- Separate cohorts per market (Israel, US, Europe), each with its own limit, instead of one shared list. Report a median per ratio per cohort, with its `n`.
- **Peer matching (decided, design D1):** a curated peer list per tracked company when one exists (MLTM: Accenture, Capgemini, Sopra Steria). Otherwise, fall back to the existing exact ISIC sub-industry match.
- API: `GET /api/companies/{ticker}/peer-benchmark` serves stored data only and never calls a provider. `POST` runs live and reports the credit estimate before it fetches anything.
- Web: a "השוואת עמיתים" tab next to Ratios that shows a table of ratios against the company, each peer and each market's median, Israel first.
- Default markets: IL, US and Europe (GB, FR, DE, NL, ES, IT). Configurable.

## Capabilities

### New Capabilities
- `peer-benchmark`: per-peer ratios, per-market cohorts and medians, cached GET and cost-announced live run.

### Modified Capabilities
- `web-client`: a new company tab.

## Impact

`services/peers.py` (cohorts, matching mode), new `services/peer_benchmark.py`, `services/ratios.py` (analyze by provider ID), `api/routers/companies.py`, schemas/OpenAPI, `web/src/features/peers/`, routes in `web/src/main.tsx`. Credits: financials cost 40 per peer. Three markets × 5 peers ≈ 600 credits, more than the 500 monthly pool, so the live run caps fetches per run and states the cost first.
