import Ajv2020 from 'ajv/dist/2020.js'
import addFormats from 'ajv-formats'
import { describe, expect, it } from 'vitest'

import full from './fixtures/mltm.full.json'
import sparse from './fixtures/mltm.sparse.json'
import schema from './company-report.schema.json'
import { fetchReport } from './queries'
import type { CompanyReport } from './types'

const ajv = new Ajv2020({ allErrors: true, strict: false })
addFormats(ajv)
const validate = ajv.compile(schema)

describe('fixtures match the spec JSON Schema', () => {
  it.each([
    ['mltm.full', full],
    ['mltm.sparse', sparse],
  ])('%s is valid', (_, fixture) => {
    const ok = validate(fixture)
    expect(validate.errors ?? []).toEqual([])
    expect(ok).toBe(true)
  })
})

describe('fixture invariants the screen relies on', () => {
  const reports = [full, sparse] as CompanyReport[]

  it.each(reports.map((r, i) => [i, r] as const))('report %i: every axis has one score per year, in order', (_, r) => {
    for (const axis of r.profile.axes) expect(axis.scores.map((s) => s.fiscal_year)).toEqual(r.years)
  })

  it.each(reports.map((r, i) => [i, r] as const))('report %i: no score is 0; first year has no trend', (_, r) => {
    for (const axis of r.profile.axes) {
      expect(axis.scores.every((s) => s.value !== 0)).toBe(true)
      expect(axis.scores[0].trend ?? null).toBeNull()
    }
  })

  it('full has 5 axes in the spec order', () => {
    expect((full as CompanyReport).profile.axes.map((a) => a.id)).toEqual([
      'stability',
      'safety',
      'growth',
      'valuation',
      'cash_quality',
    ])
  })

  it('sparse has 3 axes and one with insufficient_data and only null scores', () => {
    const axes = (sparse as CompanyReport).profile.axes
    expect(axes).toHaveLength(3)
    const missing = axes.filter((a) => a.status === 'insufficient_data')
    expect(missing).toHaveLength(1)
    expect(missing[0].scores.every((s) => s.value === null)).toBe(true)
  })
})

describe('fetchReport', () => {
  it('serves the MLTM fixture, case-insensitively', async () => {
    const r = await fetchReport('mltm', 'cached')
    expect(r.company.ticker).toBe('MLTM')
  })

  it('rejects an unknown ticker with a 404 not_found', async () => {
    await expect(fetchReport('NOPE', 'cached')).rejects.toMatchObject({ code: 'not_found', status: 404 })
  })
})
