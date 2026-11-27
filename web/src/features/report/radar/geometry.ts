/**
 * Radar geometry (spec: "גיאומטריית הרדאר"). Pure functions, no React: RadarChart only draws what
 * `radarLayout` returns. The first axis points up and axes go clockwise; SVG's y axis points down,
 * so increasing the angle from -90° turns clockwise on screen.
 */
import type { Direction, Tone } from '../types'

export const VIEW_W = 390
export const VIEW_H = 330
export const CENTER = { x: 195, y: 170 } as const
/** Radius of a score of 10. */
export const R = 96
export const LABEL_RADIUS = 136
export const GRID_LEVELS = [2, 4, 6, 8, 10] as const
export const MAX_SCORE = 10
export const MIN_AXES = 3
export const MAX_AXES = 8

/** What the chart needs per axis; it knows nothing else about the report schema. */
export interface RadarAxis {
  id: string
  label: string
  /** 1-10, or null when there is not enough data. */
  value: number | null
  trend: { direction: Direction; tone: Tone } | null
}

export interface Point {
  x: number
  y: number
}

const round = (n: number) => Math.round(n * 100) / 100

/** Angle of axis `i` of `n`, in degrees: -90 (up) for the first, then clockwise. */
export function axisAngle(i: number, n: number): number {
  return -90 + (360 / n) * i
}

/** The point at `radius` from the center along `angleDeg`, rounded to 0.01. */
export function polar(angleDeg: number, radius: number): Point {
  const a = (angleDeg * Math.PI) / 180
  return { x: round(CENTER.x + radius * Math.cos(a)), y: round(CENTER.y + radius * Math.sin(a)) }
}

/** Radius for a score: value / 10 × R, clamped to [0, 10]. */
export function scoreRadius(value: number): number {
  return (Math.min(Math.max(value, 0), MAX_SCORE) / MAX_SCORE) * R
}

export function vertex(i: number, n: number, value: number): Point {
  return polar(axisAngle(i, n), scoreRadius(value))
}

export const toPoints = (pts: Point[]) => pts.map((p) => `${p.x},${p.y}`).join(' ')

/** The grid polygon for one level (2, 4, ... 10) with `n` corners. */
export function gridRing(n: number, level: number): Point[] {
  return Array.from({ length: n }, (_, i) => vertex(i, n, level))
}

/** Offsets of the two label lines from the label point (design A2: name above, value below). */
export const LABEL_NAME_DY = -3
export const LABEL_VALUE_DY = 15

export interface LabelPlacement extends Point {
  /** Baselines of the axis name and the value line, both centered on `x`. */
  nameY: number
  valueY: number
}

/** Where an axis's label sits: centered on the label ring, name above the value. */
export function labelPlacement(i: number, n: number): LabelPlacement {
  const p = polar(axisAngle(i, n), LABEL_RADIUS)
  return { ...p, nameY: round(p.y + LABEL_NAME_DY), valueY: round(p.y + LABEL_VALUE_DY) }
}

export interface RadarLayout {
  rings: { level: number; points: string }[]
  /** Polygon through the axes that have a value, in axis order; empty under 2 values. */
  polygon: string
  vertices: { id: string; point: Point; hollow: boolean }[]
  labels: (LabelPlacement & RadarAxis)[]
}

/**
 * Everything RadarChart draws. An axis without a value gets a hollow dot on the outer ring
 * instead of a vertex, and the polygon skips it (it is never drawn as 0).
 */
export function radarLayout(axes: RadarAxis[]): RadarLayout {
  const n = axes.length
  if (n < MIN_AXES || n > MAX_AXES) throw new RangeError(`radar needs ${MIN_AXES}-${MAX_AXES} axes, got ${n}`)
  const vertices = axes.map((axis, i) =>
    axis.value === null
      ? { id: axis.id, point: vertex(i, n, MAX_SCORE), hollow: true }
      : { id: axis.id, point: vertex(i, n, axis.value), hollow: false },
  )
  const filled = vertices.filter((v) => !v.hollow).map((v) => v.point)
  return {
    rings: GRID_LEVELS.map((level) => ({ level, points: toPoints(gridRing(n, level)) })),
    polygon: filled.length >= 2 ? toPoints(filled) : '',
    vertices,
    labels: axes.map((axis, i) => ({ ...axis, ...labelPlacement(i, n) })),
  }
}

export interface HistoryLayout {
  /** Earlier years as outlines behind the front polygon: the previous year dashed, older dotted. */
  ghosts: { year: number; points: string; style: 'dashed' | 'dotted' }[]
  /** Per axis and year-on-year step, the move along the axis, colored by that year's server tone. */
  segments: { id: string; year: number; from: Point; to: Point; tone: Tone }[]
}

/**
 * The 3-year overlay. `history` holds one axes list per year in `years` (oldest first, same axis
 * order); the last one is the front year that `radarLayout` draws. No business logic: a segment's
 * tone is the server's trend tone of the later year (neutral when it sent none), and steps with a
 * missing value or no change get no segment.
 */
export function historyLayout(years: number[], history: RadarAxis[][]): HistoryLayout {
  const n = history[0]?.length ?? 0
  const ghosts: HistoryLayout['ghosts'] = []
  for (let k = 0; k < history.length - 1; k++) {
    const pts = history[k].flatMap((a, i) => (a.value === null ? [] : [vertex(i, n, a.value)]))
    if (pts.length >= 2) ghosts.push({ year: years[k], points: toPoints(pts), style: k === history.length - 2 ? 'dashed' : 'dotted' })
  }
  const segments: HistoryLayout['segments'] = []
  for (let k = 1; k < history.length; k++) {
    history[k].forEach((axis, i) => {
      const before = history[k - 1][i]?.value ?? null
      if (axis.value === null || before === null || axis.value === before) return
      segments.push({
        id: axis.id,
        year: years[k],
        from: vertex(i, n, before),
        to: vertex(i, n, axis.value),
        tone: axis.trend?.tone ?? 'neutral',
      })
    })
  }
  return { ghosts, segments }
}

/** One axis's values across the years, e.g. "6 · 6 · 7" ("—" for a missing year). */
export function historyText(history: RadarAxis[][], i: number): string {
  return history.map((axes) => axes[i]?.value ?? '—').join(' · ')
}

/** Screen-reader text for the overlay: "יציבות 2023–2025: 6, 6, 7; ...". */
export function describeRadarHistory(years: number[], history: RadarAxis[][]): string {
  const span = years.length > 1 ? ` ${years[0]}–${years[years.length - 1]}` : ''
  return (history[history.length - 1] ?? [])
    .map((axis, i) => `${axis.label}${span}: ${history.map((axes) => axes[i]?.value ?? 'אין נתונים').join(', ')}`)
    .join('; ')
}

/** Spec: with fewer than 3 axes that have a value, the screen shows the list only, no radar. */
export function hasEnoughForRadar(axes: RadarAxis[]): boolean {
  return axes.filter((a) => a.value !== null).length >= MIN_AXES
}

export const ARROWS: Record<Direction, string> = { up: '▲', down: '▼', flat: '–' }

/** Arrow colors come from the server's tone, never from the numbers. */
export const TONE_COLORS: Record<Tone, string> = {
  positive: '#15803d',
  negative: '#b91c1c',
  neutral: '#71717a',
}

export function toneColor(tone: Tone): string {
  return TONE_COLORS[tone]
}

/** Screen-reader text: every axis and its score, e.g. "יציבות 7 מתוך 10, עולה; ...". */
export function describeRadar(axes: RadarAxis[]): string {
  const dir: Record<Direction, string> = { up: 'עולה', down: 'יורד', flat: 'ללא שינוי' }
  return axes
    .map((a) => {
      if (a.value === null) return `${a.label}: אין מספיק נתונים`
      const trend = a.trend ? `, ${dir[a.trend.direction]}` : ''
      return `${a.label} ${a.value} מתוך 10${trend}`
    })
    .join('; ')
}
