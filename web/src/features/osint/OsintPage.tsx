import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CalendarX2, ExternalLink, FileText, Loader2, Play, Search, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import {
  api,
  ApiError,
  type OsintArea,
  type OsintFinding,
  type OsintLabel,
  type OsintProgress,
  type OsintResult,
} from '@/api/client'
import { postSse, type SseStream } from '@/api/sse'
import { useMode } from '@/app/mode'
import { Empty, ErrorState, Loading } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatDate, formatUsd } from '@/lib/format'

// Hebrew area names, as in the server's AREA_INFO (the API returns area ids).
const AREA_NAMES: Record<OsintArea, string> = {
  news: 'חדשות ואירועים',
  market: 'איתותי שוק',
  credit: 'דירוג אשראי ותחזיות אנליסטים',
  operations: 'תפעול וביקוש',
  labor_government: 'עבודה וממשלה',
  competition_macro: 'תחרות, מאקרו וגאופוליטיקה',
}

const LABELS: Record<OsintLabel, { text: string; variant: 'success' | 'warning' | 'destructive' | 'secondary' }> = {
  stable: { text: 'יציב', variant: 'success' },
  watch: { text: 'במעקב', variant: 'warning' },
  fragile: { text: 'שביר', variant: 'destructive' },
  insufficient_data: { text: 'אין מספיק מידע', variant: 'secondary' },
}

const CONFIDENCE: Record<OsintFinding['confidence'], string> = { high: 'ביטחון גבוה', medium: 'ביטחון בינוני', low: 'ביטחון נמוך' }

const WINDOWS = [12, 24, 36, 60]

const SIGNALS: Record<OsintFinding['signal'], string> = { positive: 'חיובי', negative: 'שלילי', neutral: 'ניטרלי' }

const STEPS: Record<OsintProgress['step'], string> = {
  orchestrator: 'מתכנן את המחקר',
  search: 'מחפש ברשת',
  area_start: 'חוקר תחום',
  area_done: 'סיים תחום',
  synthesis: 'מסכם את הממצאים',
}

/** Model text with finding ids written inline ("F3") turned into links to the numbered source. */
function LinkedText({ text }: { text: string }) {
  const parts = text.split(/\b(F\d+)\b/)
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <a key={i} href={`#source-${part}`} className="text-primary hover:underline" dir="ltr">
            {part}
          </a>
        ) : (
          part
        ),
      )}
    </>
  )
}

function LabelBadge({ label, className }: { label: OsintLabel; className?: string }) {
  const l = LABELS[label]
  return (
    <Badge variant={l.variant} className={className} data-label={label}>
      {l.text}
    </Badge>
  )
}

/** Finding numbers ("F3") as links to the numbered source. */
function Citations({ ids }: { ids: string[] }) {
  if (!ids.length) return null
  return (
    <span className="ms-1 inline-flex flex-wrap gap-1 align-middle">
      {ids.map((id) => (
        <a
          key={id}
          href={`#source-${id}`}
          className="bg-muted hover:bg-accent rounded px-1 font-mono text-[11px]"
          dir="ltr"
          data-testid="citation"
        >
          {id.replace(/^F/, '')}
        </a>
      ))}
    </span>
  )
}

function ResultView({ result }: { result: OsintResult }) {
  const card = result.scorecard
  const dropped = Object.values(result.dropped).reduce((a, b) => a + b, 0)
  return (
    <div className="space-y-6" data-testid="osint-result">
      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">
            הערכה כוללת
            <LabelBadge label={card.overall_label} className="text-sm" />
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p dir="auto" data-testid="overall-rationale">
            <LinkedText text={card.overall_rationale} />
          </p>
          <p className="text-muted-foreground text-xs" data-testid="osint-meta">
            הורץ ב-<bdi>{formatDate(result.run_date)}</bdi> · חלון מחקר{' '}
            <bdi>
              {formatDate(result.window_start)}–{formatDate(result.run_date)}
            </bdi>{' '}
            ({result.window_months} חודשים) · מודל <bdi dir="ltr">{result.model}</bdi> · חיפושים{' '}
            <bdi>
              {result.searches_used}/{result.search_limit}
            </bdi>{' '}
            · עלות <bdi>{formatUsd(result.cost_usd)}</bdi>
            {dropped > 0 && (
              <>
                {' '}
                · נפסלו <bdi>{dropped}</bdi> ממצאים (חסומים {result.dropped.blocked ?? 0}, לא מחיפוש{' '}
                {result.dropped.not_searched ?? 0}, מחוץ לחלון {result.dropped.outside_window ?? 0})
              </>
            )}
            {result.from_cache && ' · תוצאה שמורה'}
          </p>
        </CardContent>
      </Card>

      <section aria-labelledby="areas-title" className="space-y-3">
        <h2 id="areas-title" className="text-lg font-semibold">
          תחומים
        </h2>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {card.areas.map((a) => (
            <Card key={a.area} data-testid={`area-${a.area}`}>
              <CardHeader>
                <CardTitle className="flex items-center justify-between gap-2 text-base">
                  {AREA_NAMES[a.area]}
                  <LabelBadge label={a.label} />
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm" dir="auto">
                <LinkedText text={a.assessment} />
                <Citations ids={a.finding_ids} />
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <div className="grid gap-4 md:grid-cols-2">
        {(
          [
            ['risks', 'סיכונים עיקריים', card.risks],
            ['strengths', 'חוזקות עיקריות', card.strengths],
          ] as const
        ).map(([key, title, points]) => (
          <Card key={key} data-testid={`osint-${key}`}>
            <CardHeader>
              <CardTitle className="text-base">{title}</CardTitle>
            </CardHeader>
            <CardContent>
              {points.length ? (
                <ol className="list-decimal space-y-2 ps-5 text-sm">
                  {points.map((p, i) => (
                    <li key={i} dir="auto">
                      <LinkedText text={p.text} />
                      <Citations ids={p.finding_ids} />
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="text-muted-foreground text-sm">אין</p>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">סיכום</CardTitle>
        </CardHeader>
        <CardContent>
          <p dir="auto" className="leading-relaxed" data-testid="osint-summary">
            <LinkedText text={card.summary_he} />
          </p>
        </CardContent>
      </Card>

      <section aria-labelledby="sources-title" className="space-y-3">
        <h2 id="sources-title" className="text-lg font-semibold">
          מקורות ({result.findings.length})
        </h2>
        <ol className="space-y-2">
          {result.findings.map((f) => (
            <Source key={f.id} finding={f} />
          ))}
        </ol>
      </section>
    </div>
  )
}

function Source({ finding: f }: { finding: OsintFinding }) {
  return (
    <li
      id={`source-${f.id}`}
      className="target:ring-primary scroll-mt-40 rounded-lg border p-3 text-sm target:ring-2"
      data-testid="source"
      data-filing={f.derived_from_filing}
      data-undated={f.published_at == null}
    >
      <div className="flex gap-3">
        <span className="text-muted-foreground w-6 shrink-0 font-mono" dir="ltr">
          {f.id.replace(/^F/, '')}.
        </span>
        <div className="min-w-0 space-y-1">
          <p dir="auto">{f.claim}</p>
          <a
            href={f.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary inline-flex max-w-full items-center gap-1 hover:underline"
            dir="auto"
          >
            <span className="truncate">{f.source_title || f.source_url}</span>
            <ExternalLink className="size-3 shrink-0" aria-hidden />
          </a>
          <div className="text-muted-foreground flex flex-wrap items-center gap-1.5 text-xs">
            {f.published_at ? (
              <bdi>{formatDate(f.published_at)}</bdi>
            ) : (
              <Badge variant="outline" className="[&_svg]:size-3" data-testid="undated-mark">
                <CalendarX2 aria-hidden /> ללא תאריך
              </Badge>
            )}
            <span>· {AREA_NAMES[f.area]}</span>
            <span>· אות {SIGNALS[f.signal]}</span>
            <span>· {CONFIDENCE[f.confidence]}</span>
            {f.derived_from_filing && (
              <Badge variant="warning" className="[&_svg]:size-3" data-testid="filing-mark" title="המקור מצטט נתונים מהדוחות הרשמיים של החברה">
                <FileText aria-hidden /> מבוסס דוחות רשמיים
              </Badge>
            )}
          </div>
        </div>
      </div>
    </li>
  )
}

type RunStatus = 'idle' | 'confirm' | 'running'

/** The live-run action: cost warning, confirmation, streamed progress (design D9). */
function RunPanel({ ticker, months, onDone }: { ticker: string; months: number; onDone: (r: OsintResult) => void }) {
  const { mode, liveAllowed } = useMode()
  const [status, setStatus] = useState<RunStatus>('idle')
  const [progress, setProgress] = useState<OsintProgress | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [started, setStarted] = useState(0)
  const [now, setNow] = useState(0)
  const stream = useRef<SseStream | null>(null)

  useEffect(() => () => stream.current?.abort(), [])
  useEffect(() => {
    if (status !== 'running') return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [status])

  if (mode !== 'live') {
    return (
      <p className="text-muted-foreground rounded-lg border border-dashed p-3 text-sm" data-testid="osint-live-needed">
        {liveAllowed
          ? 'הרצת מחקר חדש דורשת מצב חי. עברו למצב חי כדי להריץ מחקר.'
          : 'השרת מוגדר למצב מטמון בלבד, ולכן לא ניתן להריץ מחקר חדש.'}
      </p>
    )
  }

  const start = () => {
    setStatus('running')
    setError(null)
    setProgress(null)
    setStarted(Date.now())
    setNow(Date.now())
    stream.current = postSse<OsintResult>(
      `/api/companies/${encodeURIComponent(ticker)}/osint`,
      { months },
      {
        onEvent: (event, payload) => event === 'progress' && setProgress(payload as OsintProgress),
        onDone: (r) => {
          setStatus('idle')
          onDone(r)
        },
        onError: (e) => {
          setStatus('idle')
          setError(e)
        },
      },
      { mode },
    )
  }

  const elapsed = Math.max(0, Math.round((now - started) / 1000))
  return (
    <div className="space-y-3" data-testid="osint-run">
      {status === 'idle' && (
        <Button size="sm" onClick={() => setStatus('confirm')} data-testid="osint-run-button">
          <Play aria-hidden /> הרץ מחקר חדש
        </Button>
      )}
      {status === 'confirm' && (
        <div
          role="alertdialog"
          aria-labelledby="osint-confirm-title"
          className="space-y-3 rounded-lg border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950/40"
          data-testid="osint-confirm"
        >
          <p id="osint-confirm-title" className="flex items-center gap-2 font-medium">
            <AlertTriangle className="size-4 text-amber-600" aria-hidden /> הרצת מחקר עולה כסף
          </p>
          <ul className="list-disc space-y-1 ps-5 text-sm">
            <li>המחקר מחפש ברשת מחדש בכל הרצה, ואינו משתמש בתוצאה השמורה.</li>
            <li>הוא נמשך כמה דקות ועולה בערך $1 מהקרדיט ב-OpenRouter.</li>
            <li>לאחר שהתחיל אי אפשר לעצור אותו; גם אם תעזבו את הדף, התוצאה תישמר.</li>
          </ul>
          <div className="flex gap-2">
            <Button size="sm" onClick={start} data-testid="osint-confirm-run">
              <Play aria-hidden /> אישור והרצה
            </Button>
            <Button size="sm" variant="outline" onClick={() => setStatus('idle')} data-testid="osint-cancel">
              <X aria-hidden /> ביטול
            </Button>
          </div>
        </div>
      )}
      {status === 'running' && (
        <div role="status" aria-live="polite" className="flex items-center gap-3 rounded-lg border p-3 text-sm" data-testid="osint-progress">
          <Loader2 className="size-4 animate-spin" aria-hidden />
          <div>
            <p className="font-medium">
              {progress ? STEPS[progress.step] : 'מתחיל…'}
              {progress?.area && ` · ${AREA_NAMES[progress.area]}`}
            </p>
            <p className="text-muted-foreground text-xs">
              <Search className="inline size-3" aria-hidden /> חיפושים{' '}
              <bdi>
                {progress?.searches_used ?? 0}/{progress?.search_limit ?? '—'}
              </bdi>{' '}
              · <bdi>{Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, '0')}</bdi> דקות
              {progress?.query && (
                <>
                  {' '}
                  · <bdi dir="auto">{progress.query}</bdi>
                </>
              )}
            </p>
          </div>
        </div>
      )}
      {error && <ErrorState error={error} />}
    </div>
  )
}

/** OSINT stability research for one company: the latest stored result, and a live run in live mode. */
export function OsintPage() {
  const { ticker = '' } = useParams()
  const { mode } = useMode()
  const queryClient = useQueryClient()
  const [months, setMonths] = useState(36)
  const key = ['osint', ticker, months]
  // Reading never spends, so it always asks in cached mode (the result is the same in live mode).
  const result = useQuery({ queryKey: key, queryFn: ({ signal }) => api.osint(ticker, months, 'cached', signal) })
  const notStored = result.error instanceof ApiError && result.error.code === 'not_cached'

  return (
    <section className="space-y-4" aria-labelledby="osint-title">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 id="osint-title" className="text-xl font-semibold">
            יציבות OSINT · <bdi>{ticker}</bdi>
          </h1>
          <p className="text-muted-foreground text-sm" data-testid="osint-open-sources">
            מחקר ממקורות פתוחים בלבד (חדשות, שוק, דירוגים ועוד), ולא מהדוחות הרשמיים של החברה.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            חלון זמן
            <select
              value={months}
              onChange={(e) => setMonths(Number(e.target.value))}
              className="border-input bg-background h-9 rounded-md border px-2 text-sm"
              data-testid="osint-window"
            >
              {WINDOWS.map((m) => (
                <option key={m} value={m}>
                  {m} חודשים
                </option>
              ))}
            </select>
          </label>
          <Button asChild variant="outline" size="sm">
            <Link to={`/${ticker}`}>חזרה לחברה</Link>
          </Button>
        </div>
      </div>

      <RunPanel
        key={months}
        ticker={ticker}
        months={months}
        onDone={(r) => queryClient.setQueryData(['osint', ticker, r.window_months], { ...r, from_cache: false })}
      />

      {result.isPending ? (
        <Loading label="טוען מחקר שמור…" />
      ) : notStored ? (
        <Empty title={`עוד לא הורץ מחקר OSINT לחברה זו בחלון של ${months} חודשים`}>
          {mode === 'live' && 'אפשר להריץ מחקר חדש בכפתור שלמעלה.'}
        </Empty>
      ) : result.error ? (
        <ErrorState error={result.error} onRetry={() => result.refetch()} />
      ) : (
        <ResultView result={result.data as OsintResult} />
      )}
    </section>
  )
}
