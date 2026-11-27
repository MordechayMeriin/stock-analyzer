import { Pause, Play } from 'lucide-react'
import { useEffect, useState } from 'react'

import { cn } from '@/lib/utils'

import type { CompanyReport } from '../types'
import { radarAxesForYear } from '../view'
import { RadarChart } from './RadarChart'

/** How long each year stays up; the latest year holds longer before the loop starts over. */
export const STEP_MS = 2200
export const LAST_STEP_MS = 3400

/**
 * The multi-year view: plays the years oldest to newest, the shape gliding from each year to the
 * next with the year it came from as a dashed outline, then loops. Pause/play and the year buttons
 * take over at any time; picking a year pauses on it.
 */
export function RotatingRadar({ report }: { report: CompanyReport }) {
  const { years } = report
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(true)

  useEffect(() => {
    if (!playing) return
    const last = index === years.length - 1
    const timer = setTimeout(() => setIndex((i) => (i + 1) % years.length), last ? LAST_STEP_MS : STEP_MS)
    return () => clearTimeout(timer)
  }, [playing, index, years.length])

  const year = years[index]
  const ghost = index > 0 ? radarAxesForYear(report, years[index - 1]) : undefined

  return (
    <div data-testid="rotating-radar">
      <RadarChart axes={radarAxesForYear(report, year)} ghost={ghost} />
      <div className="mt-1 flex items-center justify-center gap-2" dir="ltr">
        <button
          type="button"
          onClick={() => setPlaying((p) => !p)}
          aria-label={playing ? 'עצירת ההחלפה בין השנים' : 'הפעלת ההחלפה בין השנים'}
          className="grid size-11 place-items-center rounded-full text-foreground hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          {playing ? <Pause className="size-4" aria-hidden /> : <Play className="size-4" aria-hidden />}
        </button>
        {years.map((y, i) => (
          <button
            key={y}
            type="button"
            aria-pressed={i === index}
            aria-label={`הצגת ${y}`}
            onClick={() => {
              setIndex(i)
              setPlaying(false)
            }}
            className={cn(
              'min-h-11 rounded-md px-2 text-[15px] tabular-nums transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
              i === index ? 'font-bold text-foreground' : 'font-medium text-muted-foreground/60 hover:text-muted-foreground',
            )}
          >
            {y}
          </button>
        ))}
      </div>
      <p data-testid="rotation-caption" className="text-center text-[11px] leading-normal text-muted-foreground">
        {index > 0 ? `מקווקו: ${years[index - 1]} · החצים: השינוי מ-${years[index - 1]}` : 'השנה הראשונה בטווח'}
      </p>
    </div>
  )
}
