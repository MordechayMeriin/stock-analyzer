import { describe, expect, it } from 'vitest'

import full from '../fixtures/mltm.full.json'
import sparse from '../fixtures/mltm.sparse.json'
import type { CompanyReport } from '../types'
import { defaultYear, radarAxesForYear } from '../view'
import {
  axisAngle,
  CENTER,
  describeRadar,
  gridRing,
  hasEnoughForRadar,
  labelPlacement,
  R,
  radarLayout,
  toneColor,
  vertex,
  type RadarAxis,
} from './geometry'

const axes = (n: number, value: number | null = 5): RadarAxis[] =>
  Array.from({ length: n }, (_, i) => ({ id: `a${i}`, label: `ציר ${i}`, value, trend: null }))

describe('angles', () => {
  it('starts at the top and goes clockwise', () => {
    expect(axisAngle(0, 5)).toBe(-90)
    expect(axisAngle(1, 4)).toBe(0) // right
    expect(axisAngle(2, 4)).toBe(90) // bottom (SVG y grows downwards)
    expect(axisAngle(3, 8)).toBe(45)
  })
})

describe('vertex positions', () => {
  it('scales radius by value / 10 × R', () => {
    expect(vertex(0, 5, 10)).toEqual({ x: CENTER.x, y: CENTER.y - R })
    expect(vertex(0, 5, 5)).toEqual({ x: CENTER.x, y: CENTER.y - R / 2 })
  })

  it('puts 4 axes at the compass points, clockwise', () => {
    expect(vertex(1, 4, 10)).toEqual({ x: CENTER.x + R, y: CENTER.y })
    expect(vertex(2, 4, 10)).toEqual({ x: CENTER.x, y: CENTER.y + R })
    expect(vertex(3, 4, 10)).toEqual({ x: CENTER.x - R, y: CENTER.y })
  })

  it('clamps out-of-range scores', () => {
    expect(vertex(0, 3, 12)).toEqual(vertex(0, 3, 10))
  })
})

describe.each([3, 5, 8])('layout with %i axes', (n) => {
  const layout = radarLayout(axes(n))

  it('has five grid rings of n corners at 2/4/6/8/10', () => {
    expect(layout.rings.map((r) => r.level)).toEqual([2, 4, 6, 8, 10])
    for (const ring of layout.rings) expect(ring.points.split(' ')).toHaveLength(n)
    expect(gridRing(n, 10)[0]).toEqual({ x: CENTER.x, y: CENTER.y - R })
  })

  it('has one vertex and label per axis', () => {
    expect(layout.vertices).toHaveLength(n)
    expect(layout.labels).toHaveLength(n)
    expect(layout.polygon.split(' ')).toHaveLength(n)
  })

  it('keeps every label inside the viewBox horizontally at its anchor', () => {
    for (const l of layout.labels) {
      expect(l.x).toBeGreaterThanOrEqual(0)
      expect(l.x).toBeLessThanOrEqual(390)
    }
  })
})

describe('labels', () => {
  it('matches the design A2 label positions (name and value baselines)', () => {
    expect(labelPlacement(0, 5)).toMatchObject({ x: 195, nameY: 31, valueY: 49 })
    expect(labelPlacement(1, 5)).toMatchObject({ x: 324.34, nameY: 124.97, valueY: 142.97 })
    expect(labelPlacement(2, 5)).toMatchObject({ x: 274.94, nameY: 277.03, valueY: 295.03 })
  })
})

describe('missing values', () => {
  it('draws a hollow dot on the outer ring and leaves the axis out of the polygon', () => {
    const a = axes(4)
    a[1] = { ...a[1], value: null }
    const layout = radarLayout(a)
    expect(layout.vertices[1]).toMatchObject({ hollow: true, point: { x: CENTER.x + R, y: CENTER.y } })
    expect(layout.polygon.split(' ')).toHaveLength(3)
  })

  it('draws no polygon under two values', () => {
    expect(radarLayout(axes(3, null)).polygon).toBe('')
  })

  it('needs three values for the radar to be shown', () => {
    const a = axes(3)
    expect(hasEnoughForRadar(a)).toBe(true)
    a[0] = { ...a[0], value: null }
    expect(hasEnoughForRadar(a)).toBe(false)
  })

  it('refuses fewer than 3 or more than 8 axes', () => {
    expect(() => radarLayout(axes(2))).toThrow(RangeError)
    expect(() => radarLayout(axes(9))).toThrow(RangeError)
  })
})

describe('tone colors', () => {
  it('maps the server tone to the theme tone colors', () => {
    expect(toneColor('positive')).toBe('var(--tone-positive)')
    expect(toneColor('negative')).toBe('var(--tone-negative)')
    expect(toneColor('neutral')).toBe('var(--tone-neutral)')
  })
})

describe('report → radar axes', () => {
  const fullReport = full as CompanyReport
  const sparseReport = sparse as CompanyReport

  it('defaults to the latest year', () => {
    expect(defaultYear(fullReport)).toBe(2025)
  })

  it('takes the value and trend of the chosen year', () => {
    const [stability] = radarAxesForYear(fullReport, 2025)
    expect(stability).toEqual({
      id: 'stability',
      label: 'יציבות',
      value: 7,
      trend: { direction: 'up', tone: 'positive' },
    })
    expect(radarAxesForYear(fullReport, 2023)[0].trend).toBeNull()
  })

  it('gives an insufficient_data axis no value and no trend', () => {
    const safety = radarAxesForYear(sparseReport, 2025).find((a) => a.id === 'safety')
    expect(safety).toMatchObject({ value: null, trend: null })
  })

  it('describes every axis for screen readers', () => {
    const text = describeRadar(radarAxesForYear(sparseReport, 2025))
    expect(text).toContain('יציבות 7 מתוך 10, עולה')
    expect(text).toContain('ביטחון: אין מספיק נתונים')
  })
})
