/** Pure mapping from the report to what the screen draws for one year. No business logic. */
import type { RadarAxis } from './radar/geometry'
import type { Axis, CompanyReport, KeyMetric, ReportEvent, Score } from './types'

/** Default year: the latest one in the report. */
export function defaultYear(report: CompanyReport): number {
  return report.years[report.years.length - 1]
}

/** The radar's axes for `year`, in the server's order. insufficient_data always means no value. */
export function radarAxesForYear(report: CompanyReport, year: number): RadarAxis[] {
  return report.profile.axes.map((axis) => {
    const score = axis.scores.find((s) => s.fiscal_year === year)
    const value = axis.status === 'insufficient_data' ? null : (score?.value ?? null)
    return {
      id: axis.id,
      label: axis.label,
      value,
      trend: value === null || !score?.trend ? null : { direction: score.trend.direction, tone: score.trend.tone },
    }
  })
}

/** Events newest first; unless `showAll`, only importance >= 2 and at most `limit`. */
export function visibleEvents(events: ReportEvent[], showAll: boolean, limit = 8): ReportEvent[] {
  const sorted = [...events].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0))
  return showAll ? sorted : sorted.filter((e) => e.importance >= 2).slice(0, limit)
}

/** The metric's displayed value: the last point of its series, null when missing. */
export function lastMetricValue(metric: KeyMetric): string | null {
  return metric.series.length ? metric.series[metric.series.length - 1].value : null
}

/** The year from `?y=`, or the latest year when absent or not one of the report's years. */
export function resolveYear(report: CompanyReport, raw: string | null): number {
  const y = Number(raw)
  return raw !== null && report.years.includes(y) ? y : defaultYear(report)
}

/** The score of one axis for `year`, or undefined. */
export function scoreForYear(axis: Axis, year: number): Score | undefined {
  return axis.scores.find((s) => s.fiscal_year === year)
}
