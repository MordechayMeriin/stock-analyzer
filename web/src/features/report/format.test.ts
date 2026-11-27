import { describe, expect, it } from 'vitest'

import { formatEventDate, formatMetricValue, formatSignedPct } from './format'

describe('formatMetricValue', () => {
  it('formats currency compactly', () => {
    const s = formatMetricValue('4200000000', 'currency', 'ILS')
    expect(s).toContain('4.2')
  })
  it('treats percent as a fraction', () => {
    expect(formatMetricValue('0.082', 'percent')).toBe('8.2%')
  })
  it('formats ratio and count', () => {
    expect(formatMetricValue('1.2', 'ratio')).toBe('1.2x')
    expect(formatMetricValue('1234567', 'count')).toBe('1,234,567')
  })
  it('shows a dash for null', () => {
    expect(formatMetricValue(null, 'currency', 'ILS')).toBe('—')
  })
})

describe('formatSignedPct', () => {
  it('uses explicit signs and the real minus', () => {
    expect(formatSignedPct(12)).toBe('+12%')
    expect(formatSignedPct(-3)).toBe('−3%')
    expect(formatSignedPct(10.8)).toBe('+10.8%')
    expect(formatSignedPct(0)).toBe('0%')
  })
})

describe('formatEventDate', () => {
  it('formats day and month precision', () => {
    expect(formatEventDate('2026-02-12', 'day')).toBe('12.02.2026')
    expect(formatEventDate('2025-09', 'month')).toBe('09.2025')
  })
})
