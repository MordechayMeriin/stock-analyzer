import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Minus, Play, ShieldCheck, TrendingDown, TrendingUp } from 'lucide-react'
import { useState } from 'react'
import { useParams } from 'react-router-dom'

import { api, ApiError, type OsintFinding, type OsintPoint, type OsintResult } from '@/api/client'
import { useMode } from '@/app/mode'
import { Empty, ErrorState, Loading } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatDate, formatUsd } from '@/lib/format'

type Area = OsintFinding['area']
type AreaLabel = OsintResult['scorecard']['areas'][number]['label']

const AREA_HE: Record<Area, string> = {
  news: 'חדשות ואירועים',
  market: 'איתותי שוק',
  credit: 'דירוג אשראי ותחזיות אנליסטים',
  operations: 'תפעול וביקוש',
  labor_government: 'עבודה וממשלה',
  competition_macro: 'תחרות, מאקרו וגאופוליטיקה',
}

const LABEL_HE: Record<AreaLabel, string> = {
  stable: 'יציב',
  watch: 'למעקב',
  fragile: 'שביר',
  insufficient_data: 'אין מספיק נתונים',
}

const LABEL_VARIANT: Record<AreaLabel, 'success' | 'warning' | 'destructive' | 'outline'> = {
  stable: 'success',
  watch: 'warning',
  fragile: 'destructive',
  insufficient_data: 'outline',
}

const CONFIDENCE_HE: Record<OsintFinding['confidence'], string> = { high: 'ביטחון גבוה', medium: 'ביטחון בינוני', low: 'ביטחון נמוך' }

const WINDOWS = [12, 24, 36, 60]

function LabelBadge({ label, testId }: { label: AreaLabel; testId?: string }) {
  return (
    <Badge variant={LABEL_VARIANT[label]} data-testid={testId}>
      {LABEL_HE[label]}
    </Badge>
  )
}

/** Links to the findings a claim rests on. */
function Refs({ ids }: { ids: string[] }) {
  if (ids.length === 0) return null
  return (
    <span className="inline-flex flex-wrap gap-1 align-middle">
      {ids.map((id) => (
        <a
          key={id}
          href={`#finding-${id}`}
          className="text-primary rounded border px-1 font-mono text-xs hover:underline"
          dir="ltr"
        >
          {id}
        </a>
      ))}
    </span>
  )
}

function SignalIcon({ signal }: { signal: OsintFinding['signal'] }) {
  if (signal === 'positive')
    return <TrendingUp className="size-4 shrink-0 text-[var(--status-good)]" aria-label="חיובי" />
  if (signal === 'negative')
    return <TrendingDown className="size-4 shrink-0 text-[var(--status-critical)]" aria-label="שלילי" />
  return <Minus className="text-muted-foreground size-4 shrink-0" aria-label="ניטרלי" />
}

function PointList({ title, points, testId }: { title: string; points: OsintPoint[]; testId: string }) {
  return (
    <Card data-testid={testId}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {points.length === 0 ? (
          <p className="text-muted-foreground text-sm">לא נמצאו.</p>
        ) : (
          <ol className="list-decimal space-y-2 ps-5 text-sm">
            {points.map((p, i) => (
              <li key={i}>
                <span dir="auto">{p.text}</span> <Refs ids={p.finding_ids} />
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  )
}

function FindingItem({ f }: { f: OsintFinding }) {
  let host = f.source_url
  try {
    host = new URL(f.source_url).hostname.replace(/^www\./, '')
  } catch {
    /* keep the raw URL */
  }
  return (
    <li id={`finding-${f.id}`} className="scroll-mt-20 space-y-1 border-b py-3 last:border-b-0 target:bg-accent/50">
      <div className="flex items-start gap-2">
        <SignalIcon signal={f.signal} />
        <bdi className="text-muted-foreground font-mono text-xs" dir="ltr">
          {f.id}
        </bdi>
        <p className="text-sm" dir="auto">
          {f.claim}
        </p>
      </div>
      <div className="text-muted-foreground flex flex-wrap items-center gap-2 ps-6 text-xs">
        <a
          href={f.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary inline-flex items-center gap-1 hover:underline"
          title={f.source_title}
        >
          <bdi dir="ltr">{host}</bdi>
          <ExternalLink className="size-3" aria-hidden />
        </a>
        <span>·</span>
        <span>{f.published_at ? formatDate(f.published_at) : 'ללא תאריך'}</span>
        <span>·</span>
        <span>{CONFIDENCE_HE[f.confidence]}</span>
        {f.derived_from_filing && (
          <Badge variant="outline" title="המקור רק חוזר על נתונים מהדיווחים הרשמיים של החברה">
            מבוסס דיווח
          </Badge>
        )}
      </div>
    </li>
  )
}

function Scorecard({ result }: { result: OsintResult }) {
  const card = result.scorecard
  const byArea = new Map<Area, OsintFinding[]>()
  for (const f of result.findings) byArea.set(f.area, [...(byArea.get(f.area) ?? []), f])
  const d = result.dropped
  return (
    <div className="space-y-6">
      <Card data-testid="osint-overall">
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">
            <span>הערכה כוללת</span>
            <LabelBadge label={card.overall_label} testId="osint-overall-label" />
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p dir="auto">{card.overall_rationale}</p>
          <p className="text-muted-foreground" dir="auto">
            {card.summary_he}
          </p>
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <PointList title="סיכונים עיקריים" points={card.risks} testId="osint-risks" />
        <PointList title="חוזקות עיקריות" points={card.strengths} testId="osint-strengths" />
      </div>

      <section aria-labelledby="osint-areas-title" className="space-y-3">
        <h2 id="osint-areas-title" className="text-lg font-semibold">
          תחומים
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {card.areas.map((a) => (
            <Card key={a.area} data-testid={`osint-area-${a.area}`}>
              <CardHeader>
                <CardTitle className="flex flex-wrap items-center justify-between gap-2">
                  <span>{AREA_HE[a.area]}</span>
                  <LabelBadge label={a.label} />
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <p dir="auto">{a.assessment}</p>
                <Refs ids={a.finding_ids} />
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <section aria-labelledby="osint-findings-title" className="space-y-3">
        <h2 id="osint-findings-title" className="text-lg font-semibold">
          ממצאים ומקורות <span className="text-muted-foreground text-sm font-normal">({result.findings.length})</span>
        </h2>
        {card.areas.map((a) => {
          const findings = byArea.get(a.area) ?? []
          if (findings.length === 0) return null
          return (
            <Card key={a.area}>
              <CardHeader>
                <CardTitle className="text-base">{AREA_HE[a.area]}</CardTitle>
              </CardHeader>
              <CardContent>
                <ul>
                  {findings.map((f) => (
                    <FindingItem key={f.id} f={f} />
                  ))}
                </ul>
              </CardContent>
            </Card>
          )
        })}
        <p className="text-muted-foreground text-xs" data-testid="osint-stats">
          חיפושים: <bdi>{result.searches_used}</bdi>/<bdi>{result.search_limit}</bdi> · ממצאים שנפסלו: מקור חסום{' '}
          <bdi>{d.blocked ?? 0}</bdi>, כתובת שלא חזרה מחיפוש <bdi>{d.not_searched ?? 0}</bdi>, מחוץ לחלון הזמן{' '}
          <bdi>{d.outside_window ?? 0}</bdi> · עלות: <bdi>{result.cost_usd == null ? 'לא ידועה' : formatUsd(result.cost_usd)}</bdi>
        </p>
      </section>
    </div>
  )
}

/** OSINT stability scorecard: the latest stored research, and a live-only button to research afresh. */
export function OsintPage() {
  const { ticker = '' } = useParams()
  const { mode, liveAllowed } = useMode()
  const [months, setMonths] = useState(36)
  const queryClient = useQueryClient()
  const key = ['osint', ticker, months]
  const stored = useQuery({ queryKey: key, queryFn: ({ signal }) => api.osint(ticker, months, mode, signal) })
  const run = useMutation({
    mutationFn: () => api.runOsint(ticker, months, mode),
    onSuccess: (result) => queryClient.setQueryData(key, result),
  })
  const canRun = mode === 'live'
  const neverRun = stored.error instanceof ApiError && stored.error.code === 'not_cached'
  const result = stored.data

  const runButton = (
    <Button onClick={() => run.mutate()} disabled={!canRun || run.isPending} data-testid="osint-run">
      <Play aria-hidden /> {result ? 'הרץ מחקר מחדש' : 'הרץ מחקר'}
    </Button>
  )
  const runHint = !canRun && (
    <span className="text-muted-foreground text-sm" data-testid="osint-run-hint">
      {liveAllowed
        ? 'הרצת מחקר זמינה במצב חי בלבד.'
        : 'השרת מוגדר למצב מטמון בלבד, ולכן אפשר רק לצפות בתוצאה שמורה.'}
    </span>
  )

  return (
    <section className="space-y-6" aria-labelledby="osint-title">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <h1 id="osint-title" className="flex items-center gap-2 text-xl font-semibold">
            <ShieldCheck className="size-5" aria-hidden /> יציבות החברה ממקורות פתוחים
          </h1>
          <p className="text-muted-foreground max-w-2xl text-sm">
            מחקר OSINT: חדשות, שוק, דירוגים, תפעול, עבודה ורגולציה, תחרות ומאקרו, בלי הדיווחים הרשמיים של החברה. כל
            ממצא מקושר למקור שאומת בחיפוש.
          </p>
          {result && (
            <p className="text-muted-foreground text-xs" data-testid="osint-meta">
              <bdi>{result.company_name}</bdi> · נכון ל־<bdi>{formatDate(result.run_date)}</bdi> · חלון:{' '}
              <bdi>{formatDate(result.window_start)}</bdi> עד <bdi>{formatDate(result.run_date)}</bdi> · מודל:{' '}
              <bdi dir="ltr">{result.model}</bdi>
              {result.from_cache && (
                <>
                  {' '}
                  · <Badge variant="secondary">תוצאה שמורה</Badge>
                </>
              )}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            חלון זמן
            <select
              value={months}
              onChange={(e) => setMonths(Number(e.target.value))}
              className="border-input bg-background h-9 rounded-md border px-2 text-sm"
              data-testid="osint-window"
              disabled={run.isPending}
            >
              {WINDOWS.map((m) => (
                <option key={m} value={m}>
                  {m} חודשים
                </option>
              ))}
            </select>
          </label>
          {runButton}
        </div>
      </div>
      {runHint}

      {run.isPending && (
        <Loading label="המחקר רץ: הסוכנים מחפשים ברשת ומאמתים מקורות. זה לוקח כמה דקות…" rows={3} />
      )}
      {run.error && <ErrorState error={run.error} onRetry={() => run.mutate()} />}

      {!run.isPending &&
        (stored.isPending ? (
          <Loading label="טוען תוצאה שמורה…" />
        ) : neverRun ? (
          <Empty title={`החברה טרם נחקרה בחלון של ${months} חודשים`}>
            <p className="text-sm">הרצת מחקר עולה כסף בקריאות למודל ובחיפושים, ולוקחת כמה דקות.</p>
          </Empty>
        ) : stored.error ? (
          <ErrorState error={stored.error} onRetry={() => stored.refetch()} />
        ) : result ? (
          <Scorecard result={result} />
        ) : null)}
    </section>
  )
}
