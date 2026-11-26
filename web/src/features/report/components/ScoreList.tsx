import { useState } from 'react'

import { cn } from '@/lib/utils'

import { ARROWS, toneColor } from '../radar/geometry'
import type { Axis } from '../types'
import { scoreForYear } from '../view'
import { AxisDetail } from './AxisDetail'

export interface ScoreListProps {
  ticker: string
  axes: Axis[]
  year: number
}

function ScoreRow({ ticker, axis, year }: { ticker: string; axis: Axis; year: number }) {
  const [open, setOpen] = useState(false)
  const score = scoreForYear(axis, year)
  const value = axis.status === 'insufficient_data' ? null : (score?.value ?? null)
  const trend = value === null ? null : score?.trend
  const panelId = `axis-${axis.id}`
  return (
    <li className="border-b border-border/60 last:border-b-0">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          'flex min-h-[54px] w-full items-center justify-between gap-3 py-2 text-start',
          'focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
        )}
      >
        <span className="min-w-0">
          <span className="block text-sm font-medium">{axis.label}</span>
          {value !== null && score?.driver?.label && (
            <span className="block text-[13px] text-muted-foreground">{score.driver.label}</span>
          )}
        </span>
        {value === null ? (
          <span className="text-[13px] text-muted-foreground">אין מספיק נתונים</span>
        ) : (
          <span dir="ltr" className="flex items-baseline gap-1 text-base font-bold tabular-nums [unicode-bidi:isolate]">
            {value}
            {trend && (
              <span data-testid={`row-arrow-${axis.id}`} className="text-[11px]" style={{ color: toneColor(trend.tone) }}>
                {ARROWS[trend.direction]}
              </span>
            )}
          </span>
        )}
      </button>
      <div id={panelId} hidden={!open}>
        {open && <AxisDetail ticker={ticker} axisId={axis.id} year={year} />}
      </div>
    </li>
  )
}

export function ScoreList({ ticker, axes, year }: ScoreListProps) {
  return (
    <section aria-labelledby="why-heading" className="space-y-2">
      <h2 id="why-heading" className="text-[15px] font-semibold">
        למה כך?
      </h2>
      <ul>
        {axes.map((axis) => (
          <ScoreRow key={`${axis.id}-${year}`} ticker={ticker} axis={axis} year={year} />
        ))}
      </ul>
    </section>
  )
}
