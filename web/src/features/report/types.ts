/**
 * Company report contract (docs/company-report-spec.md, "סכמת JSON").
 *
 * Hand-written from `company-report.schema.json`, which is the spec's JSON Schema verbatim; the
 * fixture tests check every fixture against that file. Field names are snake_case as on the wire,
 * and money values are decimal strings, as in the rest of the API.
 *
 * TODO: once the server ships `GET /api/companies/{ticker}/report`, delete these types and alias
 * the generated ones from `@/api/schema` in `@/api/client`, like every other response type.
 */

export type Tone = 'positive' | 'negative' | 'neutral'
export type Direction = 'up' | 'down' | 'flat'

/** Stable axis ids. The server decides which axes appear (3 to 8) and in what order. */
export type AxisId = 'stability' | 'safety' | 'growth' | 'valuation' | 'cash_quality' | (string & {})

export interface Trend {
  direction: Direction
  delta?: number
  tone: Tone
}

export interface Driver {
  /** Up to 28 characters. */
  label: string
  tone: Tone
}

export interface Score {
  fiscal_year: number
  /** 1-10, always "higher is better". null when there is not enough data, never 0. */
  value: number | null
  sector_median?: number | null
  /** null for the first year shown (nothing to compare against). */
  trend?: Trend | null
  driver?: Driver | null
}

export interface Axis {
  id: AxisId
  /** Up to 16 characters, so labels do not collide on the radar. */
  label: string
  status: 'ok' | 'insufficient_data'
  /** Where the axis breakdown loads from when its row is opened (`?year=` is appended). */
  detail_url?: string
  scores: Score[]
}

export interface Company {
  ticker: string
  name_he: string
  name_en?: string | null
  logo_url?: string | null
  exchange?: string
  /** ISO 4217 code. */
  currency: string
  sector: { id: string; name: string }
}

export interface ReportInfo {
  type: 'annual'
  fiscal_year: number
  /** YYYY-MM-DD */
  period_end: string
  /** YYYY-MM-DD */
  published_at: string
}

export type EventType =
  | 'report'
  | 'acquisition'
  | 'leadership'
  | 'guidance'
  | 'financing'
  | 'legal'
  | 'regulatory'
  | 'buyback'
  | 'insider'
  | 'other'

export interface ReportEvent {
  id: string
  /** YYYY-MM-DD, or YYYY-MM when `date_precision` is "month". */
  date: string
  date_precision: 'day' | 'month'
  type: EventType
  /** Up to 40 characters. */
  title: string
  /** Up to 80 characters. */
  summary?: string
  /** 1-3; the screen shows importance >= 2 by default. */
  importance: 1 | 2 | 3
  tone?: Tone
  source_url?: string | null
}

export interface MetricPoint {
  fiscal_year: number
  /** Decimal string, or null when the value is missing. */
  value: string | null
}

export interface KeyMetric {
  id: string
  label: string
  format: 'currency' | 'percent' | 'ratio' | 'count'
  currency?: string
  series: MetricPoint[]
  change?: { direction: Direction; pct?: number; tone: Tone } | null
}

export interface ReportWarning {
  /** For example "stale_report". */
  code: string
  message: string
}

export interface CompanyReport {
  /** "1.x"; a breaking change bumps the major version. */
  schema_version: string
  generated_at: string
  mode: 'cached' | 'live'
  company: Company
  report: ReportInfo
  /** Up to 160 characters. */
  summary?: { text: string }
  /** 1-3 fiscal years, oldest first. */
  years: number[]
  profile: { axes: Axis[] }
  events: ReportEvent[]
  key_metrics: KeyMetric[]
  warnings?: ReportWarning[]
}

/**
 * One axis's breakdown, `GET .../report/axes/{axisId}?year=`, loaded when a row is opened.
 * The spec's example is camelCase; per the spec's naming rule it is snake_case on the wire.
 */
export interface AxisDetail {
  axis_id: AxisId
  fiscal_year: number
  /** Up to 80 characters. */
  headline: string
  /** Up to 5. */
  factors: { label: string; display: string; tone: Tone }[]
  sector_comparison?: { position: 'above' | 'below' | 'equal'; median: number } | null
  /** Plain text, no markdown. */
  text: string
}
