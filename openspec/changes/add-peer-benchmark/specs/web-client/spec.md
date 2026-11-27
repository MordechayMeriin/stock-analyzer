## ADDED Requirements

### Requirement: Peer benchmark tab
The company page SHALL offer a peer-benchmark tab next to Ratios. The tab SHALL show a ratio table with the company, each market's median and each peer, Israel first. It SHALL state the matching parameter and code and mark peers without data. In live mode it SHALL offer a run button that shows the credit estimate before anything is fetched.

#### Scenario: MLTM from stored data
- **WHEN** the user opens MLTM's benchmark tab in cached mode
- **THEN** the table shows MLTM's ratios beside its stored peers and medians, with no run button

#### Scenario: Live run confirmation
- **WHEN** the user clicks run in live mode
- **THEN** the estimated credits are shown, and nothing is fetched until the user confirms
