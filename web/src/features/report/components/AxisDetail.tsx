import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

import { useAxisDetail } from '../queries'

const POSITION: Record<'above' | 'below' | 'equal', string> = {
  above: 'מעל',
  below: 'מתחת',
  equal: 'שווה',
}

export interface AxisDetailProps {
  ticker: string
  axisId: string
  year: number
}

/** The opened breakdown of one axis. Mounted only while its row is open, so it loads on demand. */
export function AxisDetail({ ticker, axisId, year }: AxisDetailProps) {
  const query = useAxisDetail(ticker, axisId, year, true)

  if (query.isPending) {
    return (
      <div role="status" aria-label="טוען פירוט" className="space-y-2 pb-4">
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="h-4 w-2/3" />
      </div>
    )
  }
  if (query.error) {
    const missing = query.error instanceof ApiError && query.error.status === 404
    return (
      <div className="space-y-2 pb-4 text-sm text-muted-foreground">
        <p>{missing ? 'הפירוט אינו זמין לשנה זו' : 'לא הצלחנו לטעון את הפירוט'}</p>
        {!missing && (
          <Button variant="outline" size="sm" className="min-h-11" onClick={() => query.refetch()}>
            נסו שוב
          </Button>
        )}
      </div>
    )
  }

  const d = query.data
  return (
    <div className="space-y-3 pb-4 text-sm">
      <p className="font-semibold">{d.headline}</p>
      {d.factors.length > 0 && (
        <ul className="space-y-1">
          {d.factors.map((f) => (
            <li key={f.label} className="flex items-baseline justify-between gap-3">
              <span className="text-muted-foreground">{f.label}</span>
              <span dir="ltr" className="font-medium [unicode-bidi:isolate]">
                {f.display}
              </span>
            </li>
          ))}
        </ul>
      )}
      {d.sector_comparison && (
        <p className="text-[13px] text-muted-foreground">
          {POSITION[d.sector_comparison.position]} לחציון הסקטור ({d.sector_comparison.median})
        </p>
      )}
      <p className="whitespace-pre-line text-muted-foreground">{d.text}</p>
    </div>
  )
}
