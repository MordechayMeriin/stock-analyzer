# Evaluating peer selection

From `server/`, run the testing agent with the server development dependencies installed.

```sh
python -m pytest -q -s tests/unit/test_peer_evaluation.py
```

Each case invokes the real `peer-financials` Typer command. A temporary registry resolves the target, and strict HTTP mocks serve a fixed directory and empty annual statements at a reserved `.invalid` host. The test checks the selected IDs in order, domestic coverage, peer countries and domestic or international labels. A negative control reverses the selected IDs and verifies that the evaluator detects the error.

## Interpreting the report

| Case | Expected observation |
| --- | --- |
| MLTM, limit two | The fixture selects Matrix and an unreviewed issuer. ONE also has comparable operations but falls beyond the ID cutoff. Acceptance is 1/1 among reviewed selections, with one unreviewed selection and one missed business peer. |
| Synthetic grid operator, Israel only | The directory contains just the target in its Israeli class. Zero peers is the expected result. Acceptance is inapplicable because the reviewed count is zero. Establishing monopoly power would require additional market evidence. |
| Same operator, Great Britain included | Both foreign issuers meet the fixture's directory rule. The review accepts the regulated transmission operator and flags the merchant generator because its income depends on wholesale energy prices. Acceptance is 1/2. |

Acceptance divides the number of accepted selections by the total accepted and unsuitable selections. Missed IDs are independently judged suitable for the requested markets and absent from the returned set. Unreviewed means the benchmark has no business judgement for that issuer.

## Evidence and updates

Directory records and review labels live in separate versioned inputs. The MLTM profile uses the repository's target ID. Every candidate ID, class assignment, directory result and foreign scenario is synthetic. The MLTM business judgements are the testing agent's interpretation of issuer disclosures reviewed on 2026-11-26. Those disclosures describe material overlap in enterprise IT integration and services. [Malam Team services](https://www.malamteam.com/systems-integration-development/?lang=en) · [Matrix FY2025 report](https://www.matrix-globalservices.com/wp-content/uploads/Matrix_Q4_2025_Financial-statement_English.pdf) · [ONE Q3 2025 release](https://one1.global/wp-content/uploads/2025/11/ONE-Q3_2025_ENG.pdf)

When adding a case, record its directory snapshot or synthetic provenance, requested countries, limit and expected selected IDs. Review issuer activity independently, record the reviewer, date, source and reason, and list the suitable IDs in scope even if the limit excludes them. Keep issuers awaiting review out of the judgement map. [Directory inputs](../tests/fixtures/peer_directory_v1.yaml) · [Business judgements](../tests/fixtures/peer_reviews_v1.yaml)
