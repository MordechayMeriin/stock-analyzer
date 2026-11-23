# Spec Delta

## MODIFIED Requirements

### Requirement: Annual report selection
For each fiscal year the system SHALL choose exactly one full report: the fiscal year comes from the filing's fiscal-year field or the first `20\d\d` in its title; candidates must be PDF filings without "iXBRL" in the title whose title names a periodic report; the largest file wins. If no candidate exists, selection SHALL fail with an error naming the company and year.

#### Scenario: Malam FY2025
- **WHEN** the FY2025 report for Malam is selected
- **THEN** filing 32935334 is chosen, not the cover form 32935333

#### Scenario: Malam FY2024 with iXBRL wrapper
- **WHEN** the FY2024 report for Malam is selected
- **THEN** filing 63741657 is chosen, not 63728804 or the iXBRL wrapper 63741654

#### Scenario: No candidate
- **WHEN** a year has only HTM and iXBRL filings
- **THEN** selection fails with an error that names the ticker and fiscal year

#### Scenario: Trustee report is not an annual report
- **WHEN** Delek Group's only PDF filing for FY2026 is titled `דו"ח שנתי – נאמנות למחזיקי אגרות החוב (סדרה לז'), הרמטיק`
- **THEN** no report is selected for FY2026, and the error lists that filing

#### Scenario: English and Hebrew titles
- **WHEN** a year's PDF is titled `Periodic and annual report for 2025` or `דוח תקופתי ושנתי לשנת 2024`
- **THEN** it is a candidate: a title names a periodic report when it contains `תקופתי`, or `periodic` in any letter case
