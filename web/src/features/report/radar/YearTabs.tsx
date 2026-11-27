import { useRef, type KeyboardEvent } from 'react'

import { cn } from '@/lib/utils'

export interface YearTabsProps {
  years: number[]
  value: number
  onChange: (year: number) => void
}

/**
 * Year switcher (2023 | 2024 | 2025), design A2: plain text tabs, the selected one bold with a
 * dark underline. Shown LTR even in the RTL page. The visible tab is small, so an invisible
 * ::after extends each hit area past 44×44. Arrow keys move between years. Hidden for one year.
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
    <div role="tablist" aria-label="שנת דוח" dir="ltr" className="flex gap-3">
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
              'relative border-b-2 px-1 py-1.5 text-[13px] tabular-nums transition-colors',
              "after:absolute after:-inset-x-1.5 after:-inset-y-2.5 after:content-['']",
              'focus-visible:rounded-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
              selected
                ? 'border-[#09090b] font-bold text-[#09090b]'
                : 'border-transparent font-medium text-[#71717a] hover:text-[#09090b]',
            )}
          >
            {year}
          </button>
        )
      })}
    </div>
  )
}
