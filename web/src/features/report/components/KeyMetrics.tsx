import { formatMetricValue, formatSignedPct } from '../format'
import { ARROWS, toneColor } from '../radar/geometry'
import type { KeyMetric } from '../types'
import { lastMetricValue } from '../view'

const MAX_METRICS = 8

function Change({ change }: { change: NonNullable<KeyMetric['change']> }) {
  return (
    <span
      dir="ltr"
      data-testid="metric-change"
      className="inline-flex items-baseline gap-1 text-[13px] font-medium tabular-nums [unicode-bidi:isolate]"
      style={{ color: toneColor(change.tone) }}
    >
      <span className="text-[11px]">{ARROWS[change.direction]}</span>
      {change.pct !== undefined && formatSignedPct(change.pct)}
    </span>
  )
}

export function KeyMetrics({ metrics }: { metrics: KeyMetric[] }) {
  if (metrics.length === 0) return null
  return (
    <section aria-labelledby="metrics-heading" className="space-y-2">
      <h2 id="metrics-heading" className="text-[15px] font-semibold">
        מספרים עיקריים
      </h2>
      <ul>
        {metrics.slice(0, MAX_METRICS).map((m) => (
          <li
            key={m.id}
            className="flex min-h-[54px] items-center justify-between gap-3 border-b border-border/60 py-2 last:border-b-0"
          >
            <span className="text-sm">{m.label}</span>
            <span className="flex items-baseline gap-3">
              {m.change && <Change change={m.change} />}
              <span dir="ltr" className="text-base font-bold tabular-nums [unicode-bidi:isolate]">
                {formatMetricValue(lastMetricValue(m), m.format, m.currency)}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
