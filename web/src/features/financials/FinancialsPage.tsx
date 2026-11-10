import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useParams } from 'react-router-dom'

import { api } from '@/api/client'
import { useMode } from '@/app/mode'
import { QueryView } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { currencySymbol, formatDate, formatMoney, groupDecimal } from '@/lib/format'
import { cn } from '@/lib/utils'

// Counts and per-share values are not shown as money totals.
const NON_MONEY = new Set([
  'full_time_employees',
  'weighted_avg_basic_shares_outstanding',
  'weighted_avg_diluted_shares_outstanding',
  'shares_outstanding_basic',
  'shares_outstanding_diluted',
  'shares_outstanding_on_filing_date',
  'effective_tax_rate',
])

/** Normalized financial line items: one table per statement, one column per fiscal year. */
export function FinancialsPage() {
  const { ticker = '' } = useParams()
  const { mode } = useMode()
  const [asOf, setAsOf] = useState('')
  const fin = useQuery({
    queryKey: ['financials', ticker, mode, asOf],
    queryFn: ({ signal }) => api.financials(ticker, mode, asOf || undefined, signal),
  })
  return (
    <section className="space-y-4" aria-labelledby="fin-title">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 id="fin-title" className="text-xl font-semibold">
            נתונים כספיים
          </h1>
          {fin.data && (
            <p className="text-muted-foreground text-sm" data-testid="currency-label">
              מטבע הדיווח: <bdi className="font-medium">{fin.data.currency}</bdi>{' '}
              <bdi>({currencySymbol(fin.data.currency)})</bdi> · ערכים מדויקים ביחידות בסיס
            </p>
          )}
        </div>
        <label className="flex items-center gap-2 text-sm">
          זמין עד תאריך
          <Input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} className="w-40" dir="ltr" />
        </label>
      </div>
      <QueryView query={fin} isEmpty={(d) => d.years.length === 0} loadingLabel="טוען נתונים כספיים…">
        {(d) => (
          <div className="space-y-6">
            {d.statements.map((st) => (
              <div key={st.statement} className="overflow-x-auto rounded-lg border" data-testid={`statement-${st.statement}`}>
                <table className="w-full min-w-[40rem] border-collapse text-sm">
                  <caption className="bg-muted/50 px-3 py-2 text-start font-semibold">{st.label}</caption>
                  <thead>
                    <tr className="border-b">
                      <th scope="col" className="px-3 py-2 text-start font-medium">
                        סעיף
                      </th>
                      {d.years.map((y) => (
                        <th key={y} scope="col" className="px-3 py-2 text-end font-medium">
                          <bdi>FY{y}</bdi>
                          <div className="text-muted-foreground text-[10px] font-normal">זמין {formatDate(d.available_at[String(y)])}</div>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {st.items.map((it) => (
                      <tr key={it.code} className="hover:bg-muted/40 border-b last:border-0" data-code={it.code}>
                        <th scope="row" className={cn('px-3 py-1.5 text-start font-normal', it.depth > 0 && 'text-muted-foreground')}>
                          <span style={{ paddingInlineStart: `${it.depth * 0.75}rem` }}>{it.label}</span>
                        </th>
                        {d.years.map((y) => {
                          const v = it.values[String(y)]
                          const text = v == null ? '—' : NON_MONEY.has(it.code) ? groupDecimal(v) : formatMoney(v, d.currency)
                          return (
                            <td key={y} className={cn('px-3 py-1.5 text-end tabular-nums', v?.startsWith('-') && 'text-red-700 dark:text-red-400')}>
                              <bdi dir="ltr">{text}</bdi>
                              {v != null && it.as_reported[String(y)] === false && (
                                <Badge variant="outline" className="ms-1 px-1 text-[9px]" title="חושב על ידי הספק ולא נקרא מהדוח">
                                  מחושב
                                </Badge>
                              )}
                            </td>
                          )
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        )}
      </QueryView>
    </section>
  )
}
