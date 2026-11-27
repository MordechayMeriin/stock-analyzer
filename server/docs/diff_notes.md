# Report comparison notes (Malam FY2023 → FY2024 → FY2025)

Findings from the threshold spike for the business-section comparison (`stock_analyzer/diff/align.py`,
report-diff spec, design D6, task 4.4). Reports: filings 63741686 (FY2023), 63741657 (FY2024) and
32935334 (FY2025), read in cached mode from the state store. The comparison runs in about 1 second.

## How sections are matched

1. Level-2 business sections, without the "חלק ב'" part headings. Only FY2025's TOC lists the part
   headings, and they hold almost no text, so including them reported three false "new" sections.
2. Per year, against the sections aligned so far:
   - exact title keys (spelling-insensitive, digits and punctuation dropped, spaces ignored)
   - then fuzzy titles: token-set ratio, space-free ratio, or a common prefix of ≥ 4 words covering
     ≥ 60% of the shorter title (`diff_title_match_threshold`, 85)
   - then, for what is left, the same text under a different title (`diff_content_match_threshold`, 0.6)
3. Level-3 subsections are aligned the same way inside each section. A subsection that ends in one
   year is then joined with one under another section that starts in the next year, when their
   titles or texts match.

Each fix came from a real miss:

| Miss | Cause | Fix |
|---|---|---|
| Software segment not aligned FY2024 → FY2025 (score 82) | Renamed "…פרויקטים ופתרונות…" → "…פרויקטים, פתרונות… ו- AI"; the comma stayed in the key | Punctuation dropped from keys |
| "צ בר הזמנות" vs "צבר הזמנות" | Stray space inside a word (a known parsing quirk) | Space-free comparison |
| "מגבלות חיצוניות על חלוקת דיבידנדים חברות בנות…" vs "…דיבידנדים בחודש נובמ…" | Different body words glued onto both titles | Common-prefix rule |
| Subsections 3.2/3.3 "moved" from section 4 (FY2023/24) to section 3 (FY2025) | A glued paragraph "3.2. … 3.3. … 4. חלוקת דיבידנדים" puts them in section 4, since node ranges are whole paragraphs | Cross-section join; the parser limitation stays (it moves only a sentence or two) |
| A renumbered section with identical text scored 0.997 | The heading's own number was compared | Each node's leading number is dropped from its text |

After these fixes all 22 sections align across the three years, with no false new or dropped section.

## Scores per section

Text similarity is rapidfuzz `ratio` on whitespace-normalized text, with numbers kept.

| Section | FY2023→FY2024 | FY2024→FY2025 |
|---|---|---|
| פעילות החברה ותיאור התפתחות עסקיה | 0.950 | 0.833 |
| תחומי הפעילות של הקבוצה | 0.876 | 0.978 |
| השקעות בהון החברה ועסקאות במניותיה | 0.870 | 0.619 |
| חלוקת דיבידנדים | 0.658 | 0.904 |
| מידע כספי לגבי תחומי הפעילות של הקבוצה | 0.770 | 0.656 |
| סביבה כלכלית והשפעת גורמים חיצוניים | 0.841 | 0.501 |
| פעילות בתחום תשתיות וענן | 0.945 | 0.776 |
| פעילות בתחום תוכנה, פרויקטים, פתרונות עסקיים ו-AI | 0.949 | 0.875 |
| פעילות בתחום שירותי שכר, משאבי אנוש | 0.930 | 0.908 |
| פעילות בתחום הקמה והשקעה בחברות הזנק | 0.959 | 0.799 |
| מבנה ארגוני והון אנושי | 0.964 | 0.949 |
| שיווק והפצה | 0.999 | 0.992 |
| הון חוזר | 0.981 | 0.980 |
| מימון | 0.706 | 0.888 |
| רכוש קבוע ומתקנים | 0.867 | 0.951 |
| מיסוי | 0.446 | 0.986 |
| מגבלות ופיקוח על פעילות הקבוצה | 0.996 | 0.726 |
| ביטוח | 0.955 | 0.976 |
| הליכים משפטיים | 0.200 | 0.318 |
| יעדים ואסטרטגיה עסקית | 0.908 | 0.869 |
| הסדר תיחום פעילות | 0.527 | 0.522 |
| דיון בגורמי סיכון | 0.953 | 0.825 |

## Threshold choice

"Changed" pairs out of all pairs with both years present, and the characters of both versions that
would reach the change agents:

| Threshold | Sections, numbers kept | Sections, numbers masked | Subsections, numbers kept | Subsections, numbers masked |
|---|---|---|---|---|
| 0.90 | 23/44 (313K chars) | 20/44 | 85/165 (301K chars) | 80/165 |
| **0.95** | **30/44 (510K chars)** | 26/44 | **105/165 (403K chars)** | 93/165 |
| 0.98 | 39/44 (588K chars) | 38/44 | 119/165 (449K chars) | 107/165 |

**Decision: keep 0.95, with numbers kept in the compared text.**
- "Unchanged" enters the story as a fact established by code, so it must be precise. A false
  "changed" only costs tokens; a false "unchanged" hides a change.
- Masking numbers barely changes the result (except the segment financial-info section), so updated
  figures are not what makes sections differ.

## What the change agents receive

**Decision: both full versions of each changed, new or dropped subsection (design D2), as decided
after the measurements below.** The agent sees each change in its full context, at the cost of tokens
and of the LLM doing the fine-grained comparison itself.

The changed leaf sections (110 year pairs) hold 418K characters across both versions, about 139K
tokens. The actual change-agent input is larger, about 185K tokens in 5 batches: it also carries the new
and dropped sections and the paragraph-id and page labels agents cite. With the describe input (~17K),
the three directors' explanations (~30K) and the read-tool budgets (40K), a Malam FY2023–FY2025 story
is estimated at ~272K tokens. `STORY_MAX_TOKENS` defaulted to 300K; with the storyteller's web evidence
(up to ~84K more for 20 searches and the stored OSINT excerpts) the default is now 1.5M. Alternatives measured on the
changed pairs:

| Input to the change agents | Characters | ~Tokens |
|---|---|---|
| Both full versions (chosen) | 418K | 139K |
| Paragraphs that are not identical | 377K | 126K |
| Sentences that differ, ignoring spaces and punctuation | 258K | 86K |
| Only substantive edits, additions and removals (minor rewording and figures listed apart) | 140K | 47K |

Why paragraphs barely help: only 4% of the changed text matches exactly paragraph by paragraph.
PDF-conversion noise differs every year ("("הבורסה")" vs "("ה בורסה "", "מחשוב" vs "מחש וב"), and
paragraph boundaries move (87 diff blocks have a different paragraph count on each side). Of the
sentences that do differ, 47% is minor rewording (mostly the date rolling forward), 24% additions,
15% substantive edits and 13% removals. If cost or larger reports (banks, insurers) make the full
versions too expensive, the sentence-level options are the measured way down.

## What the comparison finds

New or dropped subsections, read by hand. The first group is the signal the story needs; the
rest are parsing artifacts.

- Real: FY2025 adds economic-environment topics (cheaper ICT alternatives, labour costs, new
  products, FX/inflation/interest, the "עם כלביא" and "שאגת הארי" operations), a move to a new
  Tier 3 data center in 2026, an information-security management system, and generative AI in the
  strategy. FY2024 adds the "חרבות ברזל" war impact, which FY2025 folds into a wider subsection.
- Artifacts: a few "subsections" are body sentences the subsection finder took as titles
  ("% מ-2020. מדובר בשוק…"). They have no counterpart in other years and show up as new or dropped.
