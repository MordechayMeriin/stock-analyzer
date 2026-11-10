# Report-parsing notes (Malam FY2024 / FY2025)

Findings from checking `parse_md` and `structure` against the full cached reports and the
original PDFs (task 4.7). Each quirk has a regression test; "fixture" means a trimmed slice
in `tests/fixtures/`, "synthetic" a test built from the real line.

| Quirk | Where | Handling | Test |
|---|---|---|---|
| Printed page = PDF page − 1 (not − 2 as first assumed); numbering restarts per chapter | FY2024 / FY2025 | Offset checked per numbering run; restarts recorded, not flagged | fixture + live |
| A `---` above footnotes inside one page (PDF p150) | FY2025 | Not a page break when followed by a footnote marker and no footer yet; 188 pages = PDF | fixture + synthetic + live |
| Table rows and numbered-list items at a page end look like footers | FY2025 p135, p173 | Table rows next to other rows and bare numbers after a list item are not footers | live |
| Stray space inside a word: `פרק ש לישי` | FY2024 | Chapter ordinals matched with spaces removed | synthetic |
| Number glued to a title: `12.שיווק והפצה`, `15.רכוש קבוע…` | FY2024 | Numbers at the edges of a fuzzy match are trimmed off the window | synthetic |
| Plene/defective spelling: `שירותי`/`שרותי`, `חיסכון`/`חסכון` | FY2024 vs TOC | Matching key drops internal ו/י | synthetic |
| A heading followed by `להלן` ("below") | FY2024 §6, §15 | The cross-reference guard only looks after numbers, not titles | synthetic |
| Heading lost its number: `# פעילות החברה בתחום הקמה…` | FY2025 §10 | Display number inferred from the first subsection (`10.1`) | live |
| TOC numbers ≠ body numbers (TOC 25 → body 22 for risk factors) | FY2025 | Matching by title only; body number displayed | fixture + live |
| Orphan subsection number whose title was lost: `.22.2.3` then `22.2.4. …` | FY2024 | Title left empty (shown as the number) | synthetic |
| Glued subsection title + body with no early `.`/`:` | FY2024 | plan.md rule (first `.`/`:` within 120 chars), else ≤ 60 chars at a word boundary — titles can carry a few body words | synthetic (`glued`) |
| Note headings in five layouts (plain, bold+underline, list item, `N ביאור`, reversed `title - N ביאור`); some notes have no heading at all | FY2024 / FY2025 | All five patterns; gaps reported as `note_numbers_missing` | synthetic + live |
| An auditor-report sentence mentioning "דוח רואה החשבון" | FY2025 | Auditor headings must start with `דוח` | synthetic |
| Brand/footer lines after chapter headings (`MalamTeam`, `www… | … | 0`) | both | Excluded from chapter title hints | synthetic |
