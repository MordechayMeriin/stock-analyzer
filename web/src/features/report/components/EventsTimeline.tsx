import {
  Banknote,
  Circle,
  FileText,
  GitMerge,
  Landmark,
  Repeat,
  Scale,
  TrendingDown,
  TrendingUp,
  User,
  Users,
  type LucideIcon,
} from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'

import { formatEventDate } from '../format'
import type { ReportEvent } from '../types'
import { visibleEvents } from '../view'

const ICONS: Record<Exclude<ReportEvent['type'], 'guidance'>, LucideIcon> = {
  report: FileText,
  acquisition: GitMerge,
  leadership: User,
  financing: Banknote,
  legal: Scale,
  regulatory: Landmark,
  buyback: Repeat,
  insider: Users,
  other: Circle,
}

function iconFor(e: ReportEvent): LucideIcon {
  if (e.type === 'guidance') return e.tone === 'negative' ? TrendingDown : TrendingUp
  return ICONS[e.type]
}

/** Design A2: "אירועים · 3 שנים", muted 18px stroke icons, title, summary, then the date. */
export function EventsTimeline({ events, years }: { events: ReportEvent[]; years: number }) {
  const [showAll, setShowAll] = useState(false)
  const heading = (
    <h2 id="events-heading" className="mb-4 text-[15px] font-semibold">
      אירועים{years > 1 ? ` · ${years} שנים` : ''}
    </h2>
  )
  if (events.length === 0)
    return (
      <section aria-labelledby="events-heading">
        {heading}
        <p data-testid="events-empty" className="text-[13px] text-[#71717a]">
          עדיין לא נאספו אירועים לחברה זו.
        </p>
      </section>
    )
  const shown = visibleEvents(events, showAll)
  const canExpand = !showAll && visibleEvents(events, true).length > shown.length
  return (
    <section aria-labelledby="events-heading">
      {heading}
      <ul>
        {shown.map((e) => {
          const Icon = iconFor(e)
          return (
            <li key={e.id} className="flex gap-4 pb-[22px] last:pb-0">
              <Icon aria-hidden="true" strokeWidth={1.75} className="mt-0.5 size-[18px] shrink-0 text-[#71717a]" />
              <div className="flex min-w-0 flex-col gap-0.5">
                <p className="text-sm font-semibold">{e.title}</p>
                {e.summary && <p className="text-[13px] text-[#71717a]">{e.summary}</p>}
                <p dir="ltr" className="mt-0.5 text-start text-[11px] text-[#71717a] tabular-nums [unicode-bidi:isolate]">
                  {formatEventDate(e.date, e.date_precision)}
                  {e.source_url && (
                    <>
                      {' · '}
                      <a
                        href={e.source_url}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="underline underline-offset-2 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                      >
                        מקור
                      </a>
                    </>
                  )}
                </p>
              </div>
            </li>
          )
        })}
      </ul>
      {canExpand && (
        <Button variant="ghost" className="min-h-11" onClick={() => setShowAll(true)}>
          הצג הכל
        </Button>
      )}
    </section>
  )
}
