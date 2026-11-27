import { ChevronDown } from 'lucide-react'
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
    <li>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          'flex min-h-[54px] w-full items-center gap-3 text-start',
          'focus-visible:rounded-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
        )}
      >
        <span className="min-w-[84px] text-sm font-semibold">{axis.label}</span>
        <span className="flex-1 text-[13px] text-muted-foreground">
          {value === null ? 'אין מספיק נתונים' : score?.driver?.label}
        </span>
        {value !== null && (
          <span dir="ltr" className="text-base font-bold tabular-nums [unicode-bidi:isolate]">
            {value}
            {trend && (
              <span
                data-testid={`row-arrow-${axis.id}`}
                className="ms-1 text-[11px]"
                style={{ color: toneColor(trend.tone) }}
              >
                {ARROWS[trend.direction]}
              </span>
            )}
          </span>
        )}
        <ChevronDown
          aria-hidden="true"
          className={cn('size-[18px] shrink-0 text-muted-foreground transition-transform', open && 'rotate-180')}
        />
      </button>
      <div id={panelId} hidden={!open}>
        {open && <AxisDetail ticker={ticker} axisId={axis.id} year={year} />}
      </div>
    </li>
  )
}

export function ScoreList({ ticker, axes, year }: ScoreListProps) {
  return (
    <section aria-labelledby="why-heading">
      <h2 id="why-heading" className="mb-1 text-[15px] font-semibold">
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
