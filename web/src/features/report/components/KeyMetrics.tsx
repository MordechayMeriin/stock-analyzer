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
      className="text-start text-xs font-semibold tabular-nums [unicode-bidi:isolate]"
      style={{ color: toneColor(change.tone) }}
    >
      {ARROWS[change.direction]}
      {change.pct != null && ` ${formatSignedPct(change.pct)}`}
    </span>
  )
}

/** Design A2: a two-column grid; label (12, muted), value (22/700), change (12/600, tone color). */
export function KeyMetrics({ metrics }: { metrics: KeyMetric[] }) {
  if (metrics.length === 0) return null
  return (
    <section aria-labelledby="metrics-heading">
      <h2 id="metrics-heading" className="mb-4 text-[15px] font-semibold">
        מספרים עיקריים
      </h2>
      <ul className="grid grid-cols-2 gap-x-4 gap-y-6">
        {metrics.slice(0, MAX_METRICS).map((m) => (
          <li key={m.id} className="flex min-w-0 flex-col gap-1">
            <span className="text-xs text-muted-foreground">{m.label}</span>
            <span dir="ltr" className="text-start text-[22px] font-bold tabular-nums [unicode-bidi:isolate]">
              {formatMetricValue(lastMetricValue(m), m.format, m.currency ?? undefined)}
            </span>
            {m.change && <Change change={m.change} />}
          </li>
        ))}
      </ul>
    </section>
  )
}
