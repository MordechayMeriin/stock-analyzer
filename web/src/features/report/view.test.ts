import { describe, expect, it } from 'vitest'

import full from './fixtures/mltm.full.json'
import type { CompanyReport, KeyMetric, ReportEvent } from './types'
import { lastMetricValue, resolveYear, visibleEvents } from './view'

const ev = (id: string, date: string, importance: 1 | 2 | 3): ReportEvent => ({
  id,
  date,
  date_precision: 'day',
  type: 'other',
  title: id,
  importance,
})

describe('visibleEvents', () => {
  const events = [ev('a', '2024-01-01', 3), ev('b', '2026-01-01', 1), ev('c', '2025-01-01', 2)]
  it('sorts newest first and hides importance 1 by default', () => {
    expect(visibleEvents(events, false).map((e) => e.id)).toEqual(['c', 'a'])
  })
  it('shows everything on request', () => {
    expect(visibleEvents(events, true).map((e) => e.id)).toEqual(['b', 'c', 'a'])
  })
  it('limits the default list to 8', () => {
    const many = Array.from({ length: 12 }, (_, i) => ev(`e${i}`, `2025-01-${String(i + 1).padStart(2, '0')}`, 2))
    expect(visibleEvents(many, false)).toHaveLength(8)
    expect(visibleEvents(many, false)[0].id).toBe('e11')
  })
  it('does not mutate its input', () => {
    const copy = [...events]
    visibleEvents(events, true)
    expect(events).toEqual(copy)
  })
})

describe('lastMetricValue', () => {
  it('takes the last point', () => {
    const m: KeyMetric = {
      id: 'x',
      label: 'x',
      format: 'count',
      series: [
        { fiscal_year: 2024, value: '1' },
        { fiscal_year: 2025, value: null },
      ],
    }
    expect(lastMetricValue(m)).toBeNull()
    expect(lastMetricValue({ ...m, series: [{ fiscal_year: 2025, value: '7' }] })).toBe('7')
    expect(lastMetricValue({ ...m, series: [] })).toBeNull()
  })
})

describe('resolveYear', () => {
  const report = full as CompanyReport
  it('uses a valid year, else the latest', () => {
    expect(resolveYear(report, '2024')).toBe(2024)
    expect(resolveYear(report, '1999')).toBe(2025)
    expect(resolveYear(report, 'abc')).toBe(2025)
    expect(resolveYear(report, null)).toBe(2025)
  })
})
