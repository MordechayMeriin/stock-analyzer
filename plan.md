# The Committee — implementation plan

Spec for a coding agent. Build in the order of §9; each step ends runnable and tested.

**Product:** year-over-year analysis of Israeli listed companies' periodic reports (דוח תקופתי), in Hebrew.
1. **Report diff** — the whole report, structure-aligned, noise-filtered, ranked by materiality, cited to pages.
2. **Financial analysis** — deterministic ratios, validated, compared across years, linked to management's explanations.
3. **Change feed** — one ranked list of text and ratio changes.
4. **Analyst committee** — bull, bear, risk and chair argue from 1–3; every claim cited and verified.

**Data:** FinancialFilings REST API (financialreports.eu) — report text as Markdown, statements as structured data.

---

## 0. Ground rules

- Python 3.11+: `httpx pydantic>=2 openai chromadb sentence-transformers rapidfuzz scipy numpy diskcache gradio typer pytest respx`.
- **Code fetches, parses, aligns, diffs, computes and verifies; the LLM only summarizes, scores materiality and argues.** No LLM output becomes a number, page, id or citation without a code check. Modules 1–3 run fully with `--no-llm`.
- **Direct REST calls, not the provider's MCP server** (MCP is for exploring data during development). Code fixes company, filing and `as_of`; responses are cached forever; tests run offline.
- **No PDF processing.** Text comes from the provider's Markdown, figures from its structured data. `document_url` is used only for citation links (`#page=N`).
- Agents call our tools (§5.2), never the provider.
- `Decimal` for all financial values. Point-in-time filtering in code, never in prompts.
- Hebrew text; prompts in English with Hebrew output. CLI first (`typer`); the UI calls the same functions.
- Secrets from env: `FR_API_KEY`, `OPENROUTER_API_KEY`. All thresholds and weights in `config.py`.

---

## 1. Data layer (`ingest/`)

### 1.1 Client (`fr_client.py`)
Base `https://api.financialreports.eu`, header `X-API-Key`. **Verify paths and fields against `/api/schema/` first.**

| Function | Endpoint | Credits |
|---|---|---|
| `search_companies(q)` | `GET /companies/?search=&countries=IL` | 1 |
| `list_filings(company_id)` | `GET /filings/?company=&type=10-K&ordering=-release_datetime` | 1 |
| `get_markdown(filing_id)` | `GET /filings/{id}/markdown/` (`offset`/`limit`, headers `X-Total-Chars`, `X-Next-Offset`) | 6 per call |
| `get_financials(company_id)` | company financials (expected `/companies/{id}/financials/`), `fiscal_period=FY`, all line items; once more with `include=revisions` | 40 |
| `usage()` | `GET /usage/` | 0 |

- Retries with backoff on 429/5xx (honor `Retry-After`); disk cache keyed by path + params (`--refresh` bypasses); log calls and credits to `logs/fr.jsonl`.
- Markdown: as few calls as possible (each is billed); check total length = `X-Total-Chars`. Save `data/raw/{ticker}/{fy}.md` + `.meta.json`.
- Cost per company ≈ 53–93 credits (free tier 500/month, then $0.01/credit).

### 1.2 Companies (`data/companies.yaml`)
`{ticker: MLTM, name_he: מלם תים, fr_company_id: 6901, isin: IL0001560189}`

### 1.3 Pick the report (`select.py`)
Each year has several `10-K` filings (Malam 2025: the full report 32935334, an HTM cover form 32935333; 2024: report 63741657, cover 63728804, iXBRL wrapper 63741654).
Rule: fiscal year from `fiscal_year` or the title's `20\d\d` → `file_extension == "PDF"` (metadata only: marks the full report) and no `iXBRL` in the title → largest `file_size`. `published_at = release_datetime`. Fail loudly if none.

### 1.4 Markdown → paragraphs (`parse_md.py`)
```python
class Paragraph(BaseModel):
    pid: str                 # f"{ticker}-{fy}-p{page_index:04d}-{n:03d}"
    fiscal_year: int; filing_id: int
    page_index: int          # page in the original document → citation links
    page_printed: int | None
    char_start: int; char_end: int
    raw: str; text: str      # text = normalized
    heading_level: int       # 0 = body
    in_table: bool
```
Two Markdown styles, sometimes within one company:
- **A** (Malam 2024): `<!-- page 57 -->` markers; footer `… מלם תים בע"מ **| 55 |**` (printed number = page index − 1; verified against the PDF); picture-text blocks.
- **B** (Malam 2025): pages split by a `---` line (not a table divider); footer `… מלם תים בע"מ | 57`; repeated page headers.

Detect the style → assign pages → check the printed/index offset is consistent → strip footers, picture-text blocks and lines repeated on > 30% of pages → split on blank lines (a table = one paragraph) → normalize (`normalize.py`, shared): strip bidi control chars, `**`, `<u>`, `<br>`, unify `״"` and `׳'`, unescape entities, collapse whitespace.

### 1.5 Structure tree (`structure.py`)
```python
class Node(BaseModel):
    node_id: str
    kind: Literal["chapter","section","subsection","note","auditor_report","statement","other"]
    chapter: Literal["business","directors","financials","additional","governance","other"]
    number: str | None       # display only, never used for matching
    title: str; title_norm: str
    level: int; para_range: tuple[int, int]; pages: tuple[int, int]
    children: list[str]
```
1. **Chapters** by markers: `פרק ראשון`/`תיאור עסקי` → business; `פרק שני`/`דוח הדירקטוריון` → directors; `פרק שלישי`/`דוחות כספיים` → financials; `פרק רביעי`/`פרטים נוספים` → additional; `אפקטיביות הבקרה`/`הצהרות מנהלים` → governance. Ignore matches in the table of contents.
2. **Business sections: anchored on the report's own TOC.** Parse the TOC into ordered `(number, title)` pairs and find each title in the body, in order (`token_set_ratio ≥ 85`). The title is the anchor because numbers disagree: Malam 2025's TOC says 25 for risk factors, the body says 22.
3. **Subsections** by tolerant numbering regexes. Observed forms: `22.1.1. title`, `.22.1.1 title`, `## 22.1.2 title`, `title .22.3.6`, an orphaned `.22.2.3` line, a title glued to its body (title = text up to the first `.`/`:` within 120 chars).
4. **Directors' report** by its lettered headings; **financials chapter** into the auditor's report, the primary statements and notes (`ביאור \d+`).
5. Sanity: each chapter found once, ≥ 10 business sections; log coverage. CLI `structure MLTM 2025`.

### 1.6 Retrieval index (`index.py`)
Chunks of 250–450 tokens inside one node; Chroma metadata `ticker, fiscal_year, node_id, chapter, section_title, page_start, page_end, published_ts`. Skip primary statements, keep notes. Embeddings: `BAAI/bge-m3` (cached by text hash), reused by the diff.

### 1.7 LLM client (`llm.py`)
`complete_json(model, system, user, schema, tools=None)` via OpenRouter: JSON-schema output, pydantic parse, one repair retry, disk cache, cost/latency log, a batch helper, and a `FakeLLM` for tests. Models: `MODEL_MAIN`, `MODEL_CHEAP` (§8).

---

## 2. Module 1 — Report diff (`diff/`)

```
align nodes → generic diff + specialized handler per node → noise filter → classify
  → materiality (features, then cheap LLM) → summarize top N → ReportDiff
```

### 2.0 Reference case: Malam 2024 → 2025 (first acceptance test)
Confirm by reading, then freeze in `eval/gold/MLTM_2024_2025.yaml`:
- Risk section (body §22): 16 items in 2024, 17 in 2025, each year with an impact table.
- **New risk** "סיכונים הנובעים משימוש ופיתוח טכנולוגיות בינה מלאכותית (AI)" (בינונית); it renumbers later items. Other ratings unchanged.
- Number updates: "תלות בתקציבי המדינה" (~1,589M ש"ח / 42% → ~1,635M ש"ח / 40% of revenue), wage ratios.
- Text changes: "תלות במחשב מרכזי", "סייבר ואבטחת מידע", "תמחור פרויקטים במחיר קבוע".
- Extend the gold as more sections are read (directors' report, legal proceedings first).

### 2.1 Align nodes (`align.py`)
Chapters by kind. Children of matched parents: score `0.6·title similarity + 0.4·content embedding similarity`, order-preserving alignment (Needleman–Wunsch style), accept ≥ 0.70; recurse. Unmatched → `NEW_SECTION` / `REMOVED_SECTION`; ≥ 0.65 against an already-matched node → split/merge. Notes align by title (renumbering is common).

### 2.2 Generic diff (`textdiff.py`)
1. Match paragraphs inside a node pair (`0.5·embedding + 0.5·string similarity`, order-preserving, ≥ 0.75). Unmatched paragraphs are added/removed; tables go to §2.4.
2. Sentence-diff each matched pair:
```python
class Sentence(BaseModel): text: str; pid: str
class NumberChange(BaseModel):
    old: str; new: str                        # with ±5 words of context
    old_value: Decimal | None; new_value: Decimal | None
    unit: str | None; rel_change: Decimal | None
class PairDiff(BaseModel):
    added: list[Sentence]; removed: list[Sentence]
    number_changes: list[NumberChange]
    similarity: float; hedge_delta: int
```
- Hebrew sentence splitting must keep `34.8%`, `31.12.2025`, `22.1.3`, `סעיף 6.5`, `בע"מ`, `ש"ח`, `מנכ"ל` intact.
- `difflib` on sentence lists. Replaced sentences with similarity ≥ 0.85 count as rewordings, not changes; pairs that differ only in numbers become `number_changes`.
- Numbers are parsed to `Decimal` with units (`%`, `מיליון`, `מיליארד`, `אלפי`, `ש"ח`, `דולר`…). `hedge_delta` counts hedging words (`עלול`, `ייתכן`, `מהותי`, `אי ודאות`, `החמרה`…; list in config).

### 2.3 Noise filter (`noise.py`)
Mark, don't delete:
- `ROLLFORWARD`: equal after shifting the new text's years and dates back by one year.
- `NUMBERS_UPDATED`: equal after masking numbers (kept, scored by `rel_change`).
- `COSMETIC`: similarity ≥ 0.97.
- Boilerplate nodes (cover, TOC, signatures, forward-looking disclaimers, management declarations) are excluded from ranking.

### 2.4 Table diff (`tables.py`)
- Parse Markdown tables: up to 3 header rows; the label column (usually the rightmost); `(123)` read as negative, `-` as empty.
- Align tables by caption and header, rows by label, and **columns by their year header** (new `2025|2024` vs old `2024|2023`).
- Outputs: the same year with different values in the two reports → **`RESTATED`**; `TABLE_YOY` with `rel_change`; `NEW_ROW` / `REMOVED_ROW`.

### 2.5 Handlers (`handlers/`) — extra typed changes on top of the generic diff
- **Risk factors** (`risk.py`):
  - Parse the impact table: a header with `קטנה/בינונית/גדולה` (may span several rows), category rows, and the mark (`+ X V ✓`) in the impact column.
  - Names in the table have bidi damage (`ICT-ה שינויים…`, `(AI) סיכונים…`), so compare them with `token_set_ratio`, which ignores word order.
  - **Segment items using the table rows as the canonical list**: find each name in the body, in order. Fallbacks: numbering, then LLM grouping validated by code.
  - Match items across years (title + embeddings, Hungarian, ≥ 0.75) and diff them with §2.2.
  - Change types: `RISK_NEW / RISK_REMOVED / RISK_RATING_UP / RISK_RATING_DOWN`.
- **Legal proceedings** (`legal.py`), from the legal section and the contingencies notes:
  - Split into cases by sub-numbering or markers (`תביעה`, `ייצוגית`, `בקשה לאישור`, `ערעור`, `חקירה`).
  - Extract amounts and status words.
  - Change types: `CASE_NEW / CASE_CLOSED / CASE_AMOUNT_CHANGED / CASE_STATUS_CHANGED`.
- **Auditor** (`auditor.py`):
  - A new emphasis of matter (`הפניית תשומת לב`) → `AUDITOR_EMPHASIS_NEW`.
  - Going concern (`עסק חי`) → `GOING_CONCERN`.
  - Key audit matters added or removed → `KAM_NEW / KAM_REMOVED`; a new audit firm → `AUDITOR_CHANGED`.
- **Keywords** (`keywords.py`): tag changes anywhere in the report by category:
  - covenants (`אמות מידה פיננסיות`), impairment (`ירידת ערך`), debt (`הסדר חוב`, `אג"ח`, `דירוג`), M&A (`רכישה`, `מיזוג`)
  - management (`מנכ"ל`, `מינוי`, `התפטרות`), dividends, customer dependence, guidance (`יעד`, `תחזית`)

### 2.6 Classify (`classify.py`)
After the noise filter, first match wins:
- only number changes → `NUMBERS_UPDATED`
- added text ≥ 25% of the old length, or ≥ 2 added sentences → `EXPANDED`
- the same thresholds for removed text → `REDUCED`
- anything else → `MODIFIED`

The full type list is the generic types plus the table and handler types above.

### 2.7 Materiality (`materiality.py`)
- **Stage 1, every change, deterministic:** `w_section × w_type × (1+size) × (1+|rel_change|≤1) × (1+keywords≤1.5) + 0.3·max(hedge_delta,0)`. Size = `log1p(chars changed)/8`.
  - `w_section`: auditor 5; risk, directors' report and legal 3; strategy 2.5; business and notes 2; additional 1; boilerplate 0.
  - `w_type`: GOING_CONCERN 10, AUDITOR_EMPHASIS_NEW 8, RESTATED 6, RISK_NEW and RISK_RATING_UP 5, CASE_NEW and NEW_SECTION 4, REMOVED types 3, EXPANDED 2, MODIFIED 1.5, NUMBERS_UPDATED and REDUCED 1, noise 0.
- **Stage 2, top 60, `MODEL_CHEAP` in batches of 10:** returns `{change_id, score 1–5, reason_he}` ("5 = an investor must know this"; routine updates = 1).
- **Rank** = `0.5·stage 1 (normalized) + 0.5·stage 2`. Types with `w_type ≥ 8` are pinned to the top.

### 2.8 Summaries (`summarize.py`)
Top 15 changes plus the pinned ones, `MODEL_MAIN`. Output `{summary_he ≤25 words, why_it_matters_he ≤25 words, evidence: [ids]}`; the input labels every sentence (`S1`, `R1`) and number change (`N1`).
**Guard:** every evidence id must exist, and every number in the output must appear in the input. Otherwise retry once, then fall back to a template.

### 2.9 Output
```python
class Citation(BaseModel):
    pid: str; fiscal_year: int; page_index: int; page_printed: int | None
    url: str                              # document_url#page=N
class Change(BaseModel):
    change_id: str; type: str; node_path: list[str]
    added: list[Sentence]; removed: list[Sentence]; number_changes: list[NumberChange]
    extra: dict                           # handler payload: ratings, table cells, case amounts
    keywords: list[str]; noise: bool
    score_features: float; score_llm: int | None; rank: int | None
    summary: dict | None
    citations_old: list[Citation]; citations_new: list[Citation]
class ReportDiff(BaseModel):
    ticker: str; year_old: int; year_new: int; published_new: datetime
    alignment: list[dict]; changes: list[Change]; stats: dict
```
Persist `data/diffs/{ticker}_{old}_{new}.json`. CLI: `fetch`, `structure`, `diff [--no-llm]`, `diff-debug --node`, `eval-diff`.

### 2.10 Evaluation and tests
- **Gold files:** node alignments, risk items, statuses, and a must-appear-in-top-15 list. `eval-diff` reports precision/recall and recall@15 and prints every error. Tune thresholds on gold files only, then freeze them.
- **Fixtures:** slices of the Malam reports (TOC, risk section, legal section, one table, the auditor's report). Full documents stay out of git.
- **Tests:**
  - page parsing in both styles
  - TOC-anchored sections despite mismatched numbering
  - every numbering form above
  - the sentence splitter's protected tokens
  - roll-forward or renumbering alone → no change
  - year-aligned columns and `RESTATED`
  - risk tables → 16 and 17 rows, AI risk = `RISK_NEW`, nothing else new or removed
  - the summary guard rejects an invented number

---

## 3. Module 2 — Financial analysis (`fin/`) — no LLM

### 3.1 Normalize (`normalize.py`)
`FinValue {code, statement, fiscal_year, value: Decimal, currency, as_reported (raw_value and scale both set), available_at, source_filing_id}`. Fail if the currency differs across years. Confirm codes with `/line-item-definitions/`. Codes used here (all observed for Malam FY2025):
- IS: `revenue cost_of_revenue gross_profit selling_general_administrative_expense operating_income_loss ebit ebitda net_interest_expense earnings_before_tax_including_unusual_items income_tax_expense_benefit minority_interest_in_earnings consolidated_net_income net_income_loss basic_eps`
- BS: `cash_and_equivalents total_cash_and_short_term_investments total_receivables inventory total_current_assets total_assets accounts_payable total_current_liabilities total_liabilities minority_interest total_common_equity total_equity total_debt_bs total_current_debt_bs total_non_current_debt_bs net_debt`
- CFS: `net_income_cf cash_from_operations capital_expenditure_cf cash_acquisitions_cf cash_from_investing cash_from_financing total_dividends_paid_cf net_change_in_cash_cf`
- SUP: `weighted_avg_basic_shares_outstanding shares_outstanding_on_filing_date full_time_employees`

`net_income_loss` is the parent's share (Malam: 74.0M = 77.7M consolidated − 3.7M minority interests). Use it for EPS and ROE; use `consolidated_net_income` for ROA and cash-flow ratios.

### 3.2 Data-quality checks (`checks.py`) — before any ratio
Provider data can be inconsistent. Malam FY2025 fails several identities:
- CFO + CFI + CFF = 38.9M, but the change in cash is 3.8M.
- CFI equals capex exactly, although acquisitions and intangibles purchases are listed too.
- Operating income minus interest ≠ EBT.
- Receivables of 199.6M on 4,138M revenue (DSO ≈ 18 days, implausible) leave a large unexplained part of current assets.
- Total equity < common equity, even though minority interest is positive.

```
BS1 assets = liabilities + equity          BS2 total debt = current + non-current
BS3 net debt = debt − cash & ST inv.       BS4 current assets ≥ cash+receivables+inventory, gap ≤ 40%
BS5 equity ≈ common equity + minority      IS1 gross profit = revenue − cost of revenue
IS2 net income = consolidated − minority   IS3 operating income − interest ± unusual ≈ EBT
IS4 EPS ≈ net income / shares              CF1 CFO + CFI + CFF ≈ change in cash
CF2 CFI ≠ capex when other investing items exist                CF3 net_income_cf = consolidated NI
PL1 plausibility range per ratio (e.g. DSO 5–250 days, tax rate 0–60%)
```
- A ratio with an input involved in a failed check gets `confidence="low"` and the failed check ids.
- **Cross-check:** search the financial-statements Markdown for key totals formatted in thousands (`4,138,004`). Found → confirmed, with the page.
- **Overrides:** `data/financials/overrides/{ticker}.yaml` holds `{code, fy, value, page}` and wins over provider data. Later: fill values from the statement tables via §2.4.

### 3.3 Ratios (`ratios.py`)
A declarative registry: code, Hebrew name, group, formula, inputs, unit, direction, change threshold, plausible range.
- Balance-sheet denominators use the average of opening and closing values when available.
- A zero or meaningless denominator → `None` with a reason.

| Group | Ratios (threshold) |
|---|---|
| Growth | revenue (3pp), gross profit, operating income, EBITDA (5pp), net income, EPS (10pp) |
| Profitability | gross, operating, EBITDA and net margin; SG&A/revenue (0.5pp); effective tax rate (3pp, neutral) |
| Returns | ROE = NI/avg common equity (1.5pp); ROA = consolidated NI/avg assets (0.5pp); ROIC = EBIT·(1−t)/avg(debt+equity−cash) (1pp) |
| Liquidity | current, quick = (cash+receivables)/CL (0.1), cash ratio (0.05) |
| Leverage | debt/equity (0.1), net debt/EBITDA (0.3), equity/assets (2pp), EBIT/interest (1.0), short-term share of debt (5pp) |
| Efficiency | DSO, DIO, DPO (7 days), cash conversion cycle (10), asset turnover (0.1), revenue per employee (5%) |
| Cash flow | CFO/consolidated NI (0.2), FCF = CFO + capex (10%), FCF margin (0.5pp), FCF/NI (0.2), capex/revenue (neutral), accruals = (NI−CFO)/avg assets (1pp) |
| Shareholders | payout = dividends/NI (neutral), book value per share (5%) |

Valuation ratios need share prices, which aren't in scope yet (§10).

### 3.4 Compare years (`compare.py`)
```python
class RatioValue(BaseModel):
    code: str; fiscal_year: int; value: Decimal | None
    inputs: dict[str, str]; avg_used: bool
    confidence: Literal["high","low"]; failed_checks: list[str]; reason_if_none: str | None
class RatioChange(BaseModel):
    change_id: str                          # RATIO:{code}:{old}-{new}
    code: str; name_he: str; group: str; old: RatioValue; new: RatioValue
    delta: Decimal | None                   # pp / absolute / relative, by unit
    status: Literal["IMPROVED","DETERIORATED","CHANGED","STABLE","NA"]   # CHANGED = neutral ratios
    significance: Decimal                   # |delta| / threshold
    trend_3y: Literal["up","down","flat","mixed"] | None
    explanations: list[Citation]            # §3.6
```
Every ratio for every available year (up to 5), then N vs N-1 and a 3-year trend.
**Malam FY2025 test values** (from API data):
- Margins: gross 10.47%, operating 5.30%, EBITDA 7.91%, net 1.79%
- Liquidity: current 1.18, cash 0.37
- Leverage: debt/equity 0.90, net debt/EBITDA 0.60, equity/assets 29.0%, short-term share of debt 64.7%
- Cash flow: FCF 65.5M, FCF margin 1.58%, capex/revenue 2.64%
- Expected failed checks: CF1, CF2, IS3, BS4, BS5

### 3.5 Restatements (`restatements.py`)
With `include=revisions`: a revised prior-year value from the newer report → `FIN_RESTATED`. If the API doesn't support it, rely on §2.4 `RESTATED`.

### 3.6 Management's explanations (`explain.py`)
For each change with significance ≥ 1, retrieve the top 2 directors' report paragraphs of year N. Ranking = a keyword map per line item (`הכנסות`, `רווח גולמי`, `רווח תפעולי`, `תזרים מזומנים מפעילות שוטפת`, `אשראי`, `לקוחות`…) plus embedding similarity. No LLM; shown as "the company explains".

### 3.7 Output and tests
- **Output:** `FinancialDiff {values, changes, checks, crosschecks}` → `data/fin/{ticker}_{old}_{new}.json`. CLI `fin MLTM 2024 2025`.
- **Tests:**
  - each formula, including averaging, `None` cases and sign conventions (capex and dividends are negative)
  - each check passing and failing
  - the Malam FY2025 fixture (saved API JSON) gives the values and failed checks of §3.4
  - a currency mismatch raises an error
  - point-in-time filtering on `available_at` (trap: Malam FY2023 values became available on 2024-06-13, when the iXBRL was filed, not in March with the report)

---

## 4. Module 3 — Change feed (`feed/`)

```python
class FeedItem(BaseModel):
    item_id: str; source: Literal["text","ratio","table","risk","legal","auditor","restatement"]
    title_he: str; headline_he: str; rank_score: float
    confidence: Literal["high","low"]; citations: list[Citation]; links: list[str]
```
- Ratio headlines come from code templates, e.g. `"שיעור הרווח הגולמי ירד מ-10.6% ל-10.5%"`.
- Ratio score = `w_group × min(significance,3)/3`, halved for low confidence. `w_group`: cash flow 1.2; profitability and leverage 1.0; growth 0.9; liquidity and efficiency 0.8; shareholders 0.5. Calibrate on Malam so the top 15 mixes both kinds of change.
- Deterministic links: ratio ↔ its explanation paragraphs and text changes with matching line-item keywords; risk ↔ ratios via a config map.
- CLI `feed MLTM 2024 2025 --top 20`.

---

## 5. Module 4 — Committee (`committee/`)

```
evidence pack → bull, bear, risk in parallel (tool loops) → verify → rebuttal (bull ↔ bear) → verify
  → chair: verdict, or one investigation → verify → verdict → persist
```

### 5.1 Point-in-time
Reports filtered by `published_ts ≤ as_of`; diffs and feed: the latest with `published_new ≤ as_of`; financials and ratios recomputed from values with `available_at ≤ as_of`. One test covers all three with future-dated fakes.

### 5.2 Tools (`tools.py`) — local data; `ticker` and `as_of` bound by closure
`search_reports(query, chapter="any", k=5)`, `get_changes(source=None, top=15)`, `get_ratios(group=None)`, `get_financials(codes=None)`.
Every returned item enters the run's **evidence registry** (`chunk_id`, `FIN:{code}:{fy}`, `RATIO:{code}:{fy}`, feed `item_id`). Claims may cite only registry ids.

### 5.3 Loop and evidence pack
- **Loop (`loop.py`):** a minimal custom loop. Tool calls (budget 4), then a final structured call without tools. `ROLE_TOOLS=False` runs on the evidence pack only. Emits events.
- **Evidence pack (`evidence.py`):** shared by all agents, ~6,000 tokens.
  - key ratios for 3 years, with Δ, status and low-confidence warnings
  - the top 12 feed items
  - standard queries (`k=3`): business areas, main customers and dependence, backlog, goals and strategy, the directors' explanation of revenue and profitability, liquidity and financing, operating cash flow

### 5.4 Claims and verification (`verify.py`)
```python
class Claim(BaseModel):
    claim_id: str            # assigned by code
    text_he: str             # one sentence, ≤ 35 words
    source_ids: list[str]    # 1–3 registry ids
    quote_he: str | None     # exact span, required when a chunk is cited
    kind: Literal["growth","profitability","cash_flow","balance_sheet","risk","management","other"]
    strength: Literal[1, 2, 3]
```
1. **Deterministic checks:**
   - the ids exist
   - the quote appears in the chunk (`partial_ratio ≥ 92`)
   - every number appears in the quote or matches a cited FIN/RATIO value, allowing for units and rounding (`4,138 מיליון` ↔ `4138004000`, `10.5%` ↔ `0.1047`)
   - citing a low-confidence ratio flags the claim
2. **Entailment (`MODEL_CHEAP`):** `not_supported` → rejected; `partial` → flagged, strength capped at 1.

Rejected claims are logged, never shown as evidence or passed to the chair.

### 5.5 Roles (`prompts/`)
Shared rules: use only the evidence and tool results; cite registry ids; quote exactly; never compute numbers; mention low-confidence warnings; no outside knowledge; answer in Hebrew.
- **bull:** growth, margins, returns, cash generation, backlog, strategy.
- **bear:** risk, legal, auditor and restatement changes first, then deteriorating ratios.
- **risk:** leverage, short-term debt, liquidity, coverage, data-quality warnings.
- **rebuttal:** up to 3 responses (`concede | counter | context`), verified like claims.
- **chair:** may only reference claim ids. Output `{action: verdict|investigate, investigation, verdict: BUY|HOLD|AVOID, confidence, reason_he, decisive_claim_ids (2–5, verified), what_would_change_my_mind_he}`. One investigation at most; the second call must give a verdict.

### 5.6 Flow and persistence (`flow.py`)
- `run_committee(ticker, as_of) -> Iterator[Event]`, three agents in parallel.
- Timeouts: 90s per agent, 240s per run. A failed agent is reported to the chair.
- Persist `runs/{ticker}_{as_of}_{ts}.json`: models, prompt and config hashes, registry, outputs, verification, decision, cost. `--replay` re-emits a saved run.
- **Tests** (`FakeLLM`, offline): point-in-time; each rejection rule; unit-tolerant number matching; chair retry on unverified ids; no second investigation; a full flow in < 1s.

---

## 6. UI (`ui/app.py`, Gradio)
- **Controls:** company, year pair, `as_of`, live/cached mode.
- **"מה השתנה":** the feed, with badges, headlines, why it matters, citation links, related items; routine changes collapsed.
- **"יחסים פיננסיים":** ratio table (3–5 years, Δ, arrows, warnings listing the failed checks), the company's explanations, and a data-quality panel.
- **"הדוח":** the aligned structure tree with change counts; drill-down to any section's full diff.
- **"הוועדה":** the live debate, rejected claims greyed out, rebuttals, verdict, cost.
- RTL CSS throughout. Cached mode reads saved files only.

---

## 7. Repo layout
```
app/__main__.py   config.py   llm.py
ingest/    fr_client select parse_md structure index
diff/      normalize align textdiff noise tables classify materiality summarize pipeline  handlers/{risk,legal,auditor,keywords}
fin/       normalize checks crosscheck ratios compare restatements explain
feed/      build
committee/ tools evidence loop verify flow
prompts/   header bull bear risk rebuttal chair materiality diff_summary entailment segment
ui/app.py   eval/gold/   tests/fixtures/   runs/   logs/
data/      companies.yaml  financials/overrides/   (everything else in data/ is gitignored)
```

---

## 8. Models
Before §2.7, benchmark 3–4 lean OpenRouter models against one strong reference on Malam:
- **Tasks:** materiality batches, change summaries, one bull agent.
- **Criteria:** Hebrew quality, faithfulness, valid-JSON rate, cost, latency → `docs/model_benchmark.md`.
- **Roles:** `MODEL_CHEAP` for materiality and entailment; `MODEL_MAIN` for summaries, agents and chair.
- **Target:** LLM cost per full company analysis well under $0.50.

---

## 9. Build order
1. `config.py`, `llm.py`, `FakeLLM`.
2. Client, then `fetch` Malam 2024/2025 and its financials.
3. `parse_md` (both styles) → `structure`; check the tree against the Markdown.
4. Financial analysis: normalize → checks → ratios → compare → crosscheck → `fin` CLI.
5. Retrieval index.
6. Align, generic diff, noise filter, tables, classify → `diff --no-llm`.
7. Handlers: risk (against the Malam gold), legal, auditor, keywords.
8. Gold files + `eval-diff`; tune.
9. Model benchmark → materiality stage 2 → summaries.
10. Explanations, restatements, feed. Modules 1–3 done.
11. 2–4 more companies: fix new quirks, add fixtures and gold files.
12. Committee: tools and point-in-time → evidence → verify → loop → roles → flow (fake, then real) → rebuttal, chair, persistence.
13. UI.

## 10. Later
- Parse statement tables from the Markdown to correct provider data automatically.
- A share-price source for valuation ratios (TASE Data Hub, paid).
- Quarterly (`IR`) and immediate reports: the client and the point-in-time model already support them.
