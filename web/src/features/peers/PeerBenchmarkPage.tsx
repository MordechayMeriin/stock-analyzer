import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import { useParams } from 'react-router-dom'

import { api, type PeerBenchmark, type PeerBenchmarkRun } from '@/api/client'
import { useMode } from '@/app/mode'
import { QueryView } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatRatio, type RatioUnit } from '@/lib/format'

type Peer = PeerBenchmark['company']

const STATUS_HE: Record<Peer['status'], string> = {
  ok: '',
  financials_not_cached: 'אין נתונים שמורים',
  template_not_supported: 'תבנית לא נתמכת',
  other_template: 'תבנית דיווח אחרת — לא בחציון',
}
const SOURCE_HE = { curated: 'רשימת עמיתים שנבחרה ידנית', sub_industry: 'התאמה מדויקת לסיווג ISIC' }

/** Peer benchmark: the company's latest ratios beside its peers and each market's median (web-client spec). */
export function PeerBenchmarkPage() {
  const { ticker = '' } = useParams()
  const { mode } = useMode()
  const bench = useQuery({
    queryKey: ['peer-benchmark', ticker],
    queryFn: ({ signal }) => api.peerBenchmark(ticker, mode, signal),
  })
  return (
    <section className="space-y-6" aria-labelledby="peers-title">
      <div>
        <h1 id="peers-title" className="text-xl font-semibold">
          השוואת עמיתים
        </h1>
        <p className="text-muted-foreground text-sm">
          יחסים פיננסיים לשנה האחרונה מול חברות דומות בישראל, בארה״ב ובאירופה. היחסים אינם תלויי מטבע, ולכן לא
          מבוצעת המרה.
        </p>
      </div>
      {mode === 'live' && <LiveRun ticker={ticker} />}
      <QueryView query={bench} loadingLabel="טוען השוואה…">
        {(data) => <BenchmarkTable data={data} />}
      </QueryView>
    </section>
  )
}

function LiveRun({ ticker }: { ticker: string }) {
  const qc = useQueryClient()
  const estimate = useMutation({ mutationFn: () => api.runPeerBenchmark(ticker, 'live', false) })
  const run = useMutation({
    mutationFn: () => api.runPeerBenchmark(ticker, 'live', true),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['peer-benchmark', ticker] }),
  })
  const est: PeerBenchmarkRun | undefined = estimate.data
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-3 pt-6 text-sm" data-testid="peers-live">
        {!est && (
          <Button size="sm" variant="outline" onClick={() => estimate.mutate()} disabled={estimate.isPending}>
            <Download aria-hidden /> השלמת נתונים חסרים — הערכת עלות
          </Button>
        )}
        {est && !run.data && (
          <>
            <span data-testid="peers-estimate">
              {est.financials_requests} חברות ללא נתונים כספיים · {est.metadata_requests} בקשות מטא-דאטה · עלות
              משוערת: <b>{est.estimated_credits} קרדיטים</b>
            </span>
            <Button size="sm" onClick={() => run.mutate()} disabled={run.isPending || est.estimated_credits === 0}>
              אישור והורדה
            </Button>
            <Button size="sm" variant="ghost" onClick={() => estimate.reset()}>
              ביטול
            </Button>
          </>
        )}
        {run.data && <span>הורדו נתונים ל-{run.data.fetched.length} חברות.</span>}
        {(estimate.error || run.error) && (
          <span className="text-destructive">{(estimate.error ?? run.error)?.message}</span>
        )}
      </CardContent>
    </Card>
  )
}

function BenchmarkTable({ data }: { data: PeerBenchmark }) {
  const fmt = (v: string | null | undefined, unit: string) => formatRatio(v, unit as RatioUnit)
  return (
    <div className="space-y-4">
      <p className="text-sm" data-testid="peers-match">
        בסיס ההשוואה: <b>{SOURCE_HE[data.match_parameter]}</b>
        {data.sub_industry && (
          <>
            {' '}
            · סיווג ISIC של החברה: <bdi className="font-mono">{data.sub_industry}</bdi>
            {data.sub_industry_label && <bdi> ({data.sub_industry_label})</bdi>}
          </>
        )}
        {data.reason === 'missing_sub_industry' && ' · לחברה אין סיווג ענפי אצל הספק'}
      </p>
      {data.cohorts.map((cohort) => (
        <Card key={cohort.market} data-testid={`cohort-${cohort.market}`}>
          <CardHeader>
            <CardTitle className="text-base">
              {cohort.label_he} <span className="text-muted-foreground text-xs">({cohort.countries.join(', ')})</span>
            </CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            {cohort.peers.length === 0 ? (
              <p className="text-muted-foreground text-sm">לא נמצאו חברות דומות בשוק זה.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-muted-foreground border-b text-start">
                    <th className="p-2 text-start font-medium">יחס</th>
                    <th className="p-2 text-start font-medium">
                      {data.company.ticker} <bdi className="text-xs">FY{data.company.fiscal_year}</bdi>
                    </th>
                    <th className="bg-muted/50 p-2 text-start font-medium">חציון</th>
                    {cohort.peers.map((p) => (
                      <th key={p.id} className="p-2 text-start font-medium">
                        <bdi>{p.name}</bdi>
                        <div className="text-xs font-normal">
                          {p.country}
                          {p.fiscal_year && <bdi> · FY{p.fiscal_year}</bdi>}
                          {p.currency && <bdi> · {p.currency}</bdi>}
                        </div>
                        {p.status !== 'ok' && (
                          <Badge variant="outline" className="mt-1 font-normal">
                            {STATUS_HE[p.status]}
                          </Badge>
                        )}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.ratios.map((r) => {
                    const med = cohort.medians[r.code]
                    return (
                      <tr key={r.code} className="border-b last:border-0">
                        <td className="p-2">{r.name_he}</td>
                        <td className="p-2 font-medium tabular-nums">{fmt(data.company.values[r.code], r.unit)}</td>
                        <td className="bg-muted/50 p-2 tabular-nums">
                          {fmt(med?.value, r.unit)}
                          {med && med.n > 0 && <span className="text-muted-foreground text-xs"> (n={med.n})</span>}
                        </td>
                        {cohort.peers.map((p) => (
                          <td key={p.id} className="p-2 tabular-nums">
                            {fmt(p.values[r.code], r.unit)}
                          </td>
                        ))}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
