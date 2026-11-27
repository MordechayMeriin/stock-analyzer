# Tasks

## 1. Research subject and access

- [x] 1.1 Resolve a tracked ticker's class through the existing company profile client. Preserve leading zeroes and return a clear missing-class result. Verify an unknown ticker issues zero provider calls and an unclassified ticker issues zero searches.
- [x] 1.2 Add the market subject and cache lifecycle using the existing live guard. Test default Israel, Europe, and the United States, market subset normalization, invalid inputs, cache isolation between scopes and modes, and replay with no provider access.

## 2. OSINT market brief

- [x] 2.1 Build the market-specific brief using the OSINT search backend, blocklist, shared budget, citation checks, and usage logging. Verify market coverage under a single search limit, blocked URLs, unverified citations, and sparse evidence using scripted offline responses.
- [x] 2.2 Add the three market sections and preserve source scope for statistics and concentration claims. Verify class 6220 with fixed metadata, a sourced private operator, an EU-only statistic labelled with its actual coverage, and a broader or differently classified figure shown as context.

## 3. Command and integration

- [x] 3.1 Add and document `market-research TICKER` with mode, repeatable market, months, and JSON options. Use Typer CliRunner to verify the ticker-to-class flow through final output and ensure direct class input is available only to the offline test service boundary.
- [x] 3.2 Verify the market CLI, peer selection, and existing company OSINT regressions. Assert the market research flow sends no financial, filing, or report-text requests.
