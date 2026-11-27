# Spec Delta

## ADDED Requirements

### Requirement: Report page loads from the API
The report page SHALL load a tracked company's report and its axis details from the report API in the current mode. It SHALL keep serving the MLTM and SPARSE fixtures as dev data. When the API reports that a report is not cached, the page SHALL say so and offer to build it in live mode where live mode is allowed.

#### Scenario: El Al report
- **WHEN** the user opens the report page for ELAL and its report is saved
- **THEN** the radar shows the five axes for the latest year, and opening an axis row loads its detail from the API

#### Scenario: Not cached
- **WHEN** the API answers not cached for the ticker
- **THEN** the page shows that no report has been built yet, with a build action in live mode
