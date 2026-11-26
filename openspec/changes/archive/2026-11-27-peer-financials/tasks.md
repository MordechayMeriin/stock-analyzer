# Tasks

## 1. Directory discovery

- [x] 1.1 Add cached/live company profile and filtered directory reads to the provider client. Verify exact query parameters, pagination, missing metadata and cache misses against offline HTTP fixtures. Document the profile fields and directory filters in the provider API notes.
- [x] 1.2 Implement Israel-first selection and optional international selection in the peer service. Verify exact numeric ID order across shuffled pages, eligibility checks, duplicate and target exclusion, partial cohorts and the maximum selected count.
- [x] 1.3 Test the sole domestic operator, optional foreign fill, incomplete discovery and absent classification. Assert distinct coverage outcomes and the absence of unnecessary directory and financial requests.

## 2. Annual financials and runner

- [x] 2.1 Share statement formatting between tracked and provider-ID financials. Compare output for the same fixture and verify existing financials tests, decimal values, missing years and currency checks.
- [x] 2.2 Add the Typer runner, machine-readable selection context, repeatable foreign-country option, limit validation and mode handling. Document both invocations and verify with CliRunner that omitting foreign countries queries only IL, even for a target with a different or missing country. Verify that named foreign countries can fill remaining places.
- [x] 2.3 Drive the runner from target lookup to output using strict HTTP mocks. Assert the exact selected issuers, one annual read per selected issuer on a cache miss, native currencies and successful cached replay with zero network requests. Fail the test on filings, Markdown, or registry edits.

## 3. Testing agent

- [x] 3.1 Create versioned benchmark inputs and independent reviewed issuer judgements with dated sources and business reasons. Include MLTM and a sole-operator scenario. Mark synthetic cases explicitly and leave unreviewed candidates distinguishable from rejected ones.
- [x] 3.2 Add a repeatable pytest evaluation that invokes the real runner, reports accepted, unsuitable, missed and unreviewed issuer IDs, and handles an expected empty domestic cohort. Verify that an intentionally wrong selection fails its expected-ID check and that a same-class foreign issuer with a different operating model is flagged by the business review.
- [x] 3.3 Document the evaluator command, run it offline from the server directory and verify that its output explains the monopoly fixture and the foreign-analogue judgements.
