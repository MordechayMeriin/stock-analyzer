import { useQuery } from '@tanstack/react-query'

import { api } from '@/api/client'
import { useMode } from '@/app/mode'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatUsd } from '@/lib/format'

interface FreeCredits {
  limit?: number
  used?: number
  remaining?: number
}

/** Provider credit usage (from the provider, or the last value seen) and LLM spend from the logs. */
export function UsagePanel() {
  const { mode } = useMode()
  const usage = useQuery({ queryKey: ['usage', mode], queryFn: ({ signal }) => api.usage(mode, signal) })
  const free = (usage.data?.provider?.free_credits ?? null) as FreeCredits | null
  return (
    <Card className="gap-3 py-4" data-testid="usage-panel">
      <CardHeader className="px-4">
        <CardTitle className="text-sm">שימוש וקרדיטים</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1.5 px-4 text-sm">
        {usage.isPending && <p className="text-muted-foreground">טוען…</p>}
        {usage.error && <p className="text-destructive">לא ניתן לטעון נתוני שימוש</p>}
        {usage.data && (
          <>
            {free ? (
              <p>
                קרדיטים אצל ספק הדוחות:{' '}
                <bdi dir="ltr" className="font-medium">
                  {free.used ?? '?'} / {free.limit ?? '?'}
                </bdi>{' '}
                (נותרו <bdi className="font-medium">{free.remaining ?? '?'}</bdi>)
              </p>
            ) : (
              <p className="text-muted-foreground">
                קרדיטים אצל הספק: {usage.data.provider_error ? 'לא זמין במצב הנוכחי' : 'אין נתונים'}
              </p>
            )}
            <p className="text-muted-foreground">
              קריאות לספק ביומן: <bdi>{usage.data.fr_log.network_calls ?? 0}</bdi>, קרדיטים שנרשמו:{' '}
              <bdi>{usage.data.fr_log.credits_logged ?? 0}</bdi>
            </p>
            <p className="text-muted-foreground">
              עלות LLM מצטברת: <bdi dir="ltr">{formatUsd(Number(usage.data.llm.total_cost_usd ?? 0))}</bdi> (
              <bdi>{usage.data.llm.calls ?? 0}</bdi> קריאות)
            </p>
          </>
        )}
      </CardContent>
    </Card>
  )
}
