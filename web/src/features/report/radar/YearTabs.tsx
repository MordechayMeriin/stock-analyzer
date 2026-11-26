import { useRef, type KeyboardEvent } from 'react'

import { cn } from '@/lib/utils'

export interface YearTabsProps {
  years: number[]
  value: number
  onChange: (year: number) => void
}

/**
 * Year switcher (2023 | 2024 | 2025). Shown LTR even in the RTL page, so years read oldest to
 * newest. Tabs pattern: arrow keys move between years, 44×44 minimum hit area. Hidden for one year.
 */
export function YearTabs({ years, value, onChange }: YearTabsProps) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  if (years.length < 2) return null

  const onKeyDown = (e: KeyboardEvent, i: number) => {
    const last = years.length - 1
    const next =
      e.key === 'ArrowRight' ? Math.min(i + 1, last) : e.key === 'ArrowLeft' ? Math.max(i - 1, 0) : e.key === 'Home' ? 0 : e.key === 'End' ? last : null
    if (next === null) return
    e.preventDefault()
    onChange(years[next])
    refs.current[next]?.focus()
  }

  return (
    <div role="tablist" aria-label="שנת דוח" dir="ltr" className="inline-flex gap-1 rounded-md bg-muted p-1">
      {years.map((year, i) => {
        const selected = year === value
        return (
          <button
            key={year}
            ref={(el) => {
              refs.current[i] = el
            }}
            type="button"
            role="tab"
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(year)}
            onKeyDown={(e) => onKeyDown(e, i)}
            className={cn(
              'min-h-11 min-w-11 rounded-sm px-3 text-sm font-medium tabular-nums transition-colors',
              'focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
              selected ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {year}
          </button>
        )
      })}
    </div>
  )
}
