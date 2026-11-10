import { AlertTriangle, Inbox, RefreshCw, Zap } from 'lucide-react'
import type { ReactNode } from 'react'

import { ApiError } from '@/api/client'
import { useMode } from '@/app/mode'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

export function Loading({ label = 'טוען…', rows = 4 }: { label?: string; rows?: number }) {
  return (
    <div role="status" aria-live="polite" className="space-y-3">
      <span className="text-muted-foreground text-sm">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-5" style={{ width: `${90 - i * 12}%` }} />
      ))}
    </div>
  )
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="text-muted-foreground flex flex-col items-center gap-2 rounded-lg border border-dashed p-8 text-center">
      <Inbox className="size-6" aria-hidden />
      <p className="text-foreground font-medium">{title}</p>
      {children}
    </div>
  )
}

const MESSAGES: Record<string, string> = {
  not_cached: 'הנתונים המבוקשים אינם שמורים במטמון המקומי.',
  live_disabled: 'הפעולה דורשת מצב חי.',
  network_error: 'השרת אינו זמין.',
  selection_too_large: 'הקטע שנבחר גדול מדי.',
}

/** The API's error message with a retry action; "not cached" offers a live fetch when allowed. */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { liveAllowed, mode, setMode } = useMode()
  const apiError = error instanceof ApiError ? error : null
  const code = apiError?.code ?? 'error'
  const needsLive = code === 'not_cached' || code === 'live_disabled'
  return (
    <div role="alert" className="border-destructive/40 bg-destructive/5 flex flex-col gap-3 rounded-lg border p-4">
      <div className="flex items-start gap-2">
        <AlertTriangle className="text-destructive mt-0.5 size-5 shrink-0" aria-hidden />
        <div className="space-y-1">
          <p className="font-medium">{MESSAGES[code] ?? 'הבקשה נכשלה.'}</p>
          <p className="text-muted-foreground text-sm" dir="auto">
            {apiError?.message ?? String((error as Error)?.message ?? error)}
          </p>
          <p className="text-muted-foreground font-mono text-xs" dir="ltr">
            {code}
          </p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {needsLive && liveAllowed && mode === 'cached' && (
          <Button size="sm" onClick={() => setMode('live')}>
            <Zap aria-hidden /> עבור למצב חי וטען מהספק
          </Button>
        )}
        {needsLive && !liveAllowed && (
          <span className="text-muted-foreground text-sm">
            השרת מוגדר למצב מטמון בלבד, ולכן לא ניתן להביא נתונים חדשים.
          </span>
        )}
        {onRetry && (
          <Button size="sm" variant="outline" onClick={onRetry}>
            <RefreshCw aria-hidden /> נסה שוב
          </Button>
        )}
      </div>
    </div>
  )
}

interface QueryLike<T> {
  data: T | undefined
  isPending: boolean
  error: unknown
  refetch: () => unknown
}

/** Render a query result with the shared loading / error / empty states. */
export function QueryView<T>({
  query,
  isEmpty,
  empty,
  loadingLabel,
  children,
}: {
  query: QueryLike<T>
  isEmpty?: (data: T) => boolean
  empty?: ReactNode
  loadingLabel?: string
  children: (data: T) => ReactNode
}) {
  if (query.isPending) return <Loading label={loadingLabel} />
  if (query.error) return <ErrorState error={query.error} onRetry={() => query.refetch()} />
  const data = query.data as T
  if (isEmpty?.(data)) return <>{empty ?? <Empty title="אין נתונים להצגה" />}</>
  return <>{children(data)}</>
}
