/** Pure display formatting for the company screen. Values come from the server; nothing is computed. */
import type { KeyMetric } from './types'

const MINUS = '−'

export function formatMetricValue(value: string | null, format: KeyMetric['format'], currency?: string): string {
  if (value === null) return '—'
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  switch (format) {
    case 'currency':
      return new Intl.NumberFormat('he-IL', {
        style: 'currency',
        currency: currency ?? 'ILS',
        notation: 'compact',
        maximumFractionDigits: 1,
      }).format(n)
    case 'percent':
      return `${new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(n * 100)}%`
    case 'ratio':
      return `${new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(n)}x`
    case 'count':
      return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(n)
  }
}

/** "+12%", "−3%" (U+2212), "0%". */
export function formatSignedPct(pct: number): string {
  const body = `${new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(Math.abs(pct))}%`
  return pct > 0 ? `+${body}` : pct < 0 ? `${MINUS}${body}` : body
}

/** day: "2026-02-12" -> "12.02.2026"; month: "2025-09" -> "09.2025". */
export function formatEventDate(date: string, precision: 'day' | 'month'): string {
  const [y, m, d] = date.split('-')
  return precision === 'month' ? `${m}.${y}` : `${d}.${m}.${y}`
}
