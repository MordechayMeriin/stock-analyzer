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
import { toneColor } from '../radar/geometry'
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

export function EventsTimeline({ events }: { events: ReportEvent[] }) {
  const [showAll, setShowAll] = useState(false)
  if (events.length === 0) return null
  const shown = visibleEvents(events, showAll)
  const canExpand = !showAll && visibleEvents(events, true).length > shown.length
  return (
    <section aria-labelledby="events-heading" className="space-y-3">
      <h2 id="events-heading" className="text-[15px] font-semibold">
        אירועים
      </h2>
      <ul className="space-y-4">
        {shown.map((e) => {
          const Icon = iconFor(e)
          return (
            <li key={e.id} className="flex gap-3">
              <Icon
                aria-hidden="true"
                className="mt-0.5 size-5 shrink-0"
                style={{ color: e.type === 'guidance' && e.tone ? toneColor(e.tone) : undefined }}
              />
              <div className="min-w-0 space-y-0.5">
                <p className="text-sm font-medium">{e.title}</p>
                <p dir="ltr" className="text-start text-xs text-muted-foreground tabular-nums [unicode-bidi:isolate]">
                  {formatEventDate(e.date, e.date_precision)}
                </p>
                {e.summary && <p className="text-[13px] text-muted-foreground">{e.summary}</p>}
                {e.source_url && (
                  <a
                    href={e.source_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex min-h-11 items-center text-[13px] underline underline-offset-2 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                  >
                    מקור
                  </a>
                )}
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
