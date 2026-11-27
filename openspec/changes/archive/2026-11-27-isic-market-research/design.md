# Design

## Context

The company OSINT pipeline uses one tracked ticker and produces a stability scorecard from verified web findings. Peer selection already reads the FinancialFilings company profile and exposes its `sub_industry.code`.

## Goals / Non-Goals

The output is a market brief for the class and markets identified by the request. Company OSINT and its existing result format retain their current behavior.

## Decisions

1. Add `stock-analyzer market-research TICKER --months 36 --json`. Default to Israel, Europe, and the United States, the configured OSINT window, and cached mode. Use repeatable `--market` options (`IL`, `EUROPE`, `US`) to narrow the run to an explicit set. Require `--mode live` for fresh research and use the existing live guard. Resolve the ticker through the tracked registry, then obtain the class using the same company-profile method as peer selection. Keep the class code as a string. Direct class injection belongs to the offline test boundary.
2. Define a market subject with ticker, class, normalized market set, and window. Search each requested market with the class activity name and relevant local terms. Use the ISIC code as the common scope anchor. Record the geography, classification, period, and coverage of quantitative evidence. Europe is a regional scope. A country-specific or EU-only source retains that narrower coverage.
3. Reuse the OSINT search backend, search limits, source blocklist, citation allowlist, and usage logging. Use market-specific instructions and output for demand and growth, market participants and competition, and regulation and risks. Allocate initial searches across requested markets before spending remaining searches on follow-ups. Honor the existing total search cap, report gaps by market, and filter uncited claims. The preflight company profile is the only FinancialFilings read on the fresh research path.
4. Save successful results in the existing state store under a market-research key with normalized ticker, deduplicated and canonically ordered market set, and window. Keep the resolved class in the saved result. A cached read resolves the tracked ticker locally and reads the saved report without querying FinancialFilings or the web. Isolate fake results from live results.

## Risks / Trade-offs

- Public statistics may use local or older classification schemes. Keep the original coverage and identify broader figures as context unless sources document a mapping.
- Cross-market totals and rankings require compatible class coverage, periods, units, and actual geographies. Compare only supported figures and describe the available evidence where measures differ.
- A single listed issuer can coexist with private competitors. Assess concentration only with evidence for both the market definition and shares.
- Source hits can be sparse. Return a cited partial brief with evidence gaps when available evidence supports only some sections.
