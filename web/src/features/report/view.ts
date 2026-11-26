/** Pure mapping from the report to what the screen draws for one year. No business logic. */
import type { RadarAxis } from './radar/geometry'
import type { CompanyReport } from './types'

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
