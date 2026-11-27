import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, BookOpen, Globe, Newspaper, Sparkles, Square } from 'lucide-react'
import { useId, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import {
  api,
  ApiError,
  type StoryCitation,
  type StoryFact,
  type StoryProgress,
  type StoryRun,
  type StorySegment,
  type StoryWebSource,
} from '@/api/client'
import { postSse, type SseStream } from '@/api/sse'
import { useMode } from '@/app/mode'
import { Empty, ErrorState, Loading } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { currencySymbol, formatDate, formatUsd, groupDecimal, pageLabel } from '@/lib/format'
import { cn } from '@/lib/utils'

type Facts = Map<string, StoryFact>
type Sources = Record<string, StoryWebSource>

const UNKNOWN_DATE = 'תאריך לא ידוע'

/** The excerpt a web number was quoted from, with the quote highlighted (whitespace-insensitive). */
function QuotedExcerpt({ quote, excerpts }: { quote: string; excerpts: string[] }) {
  const norm = (t: string) => t.split(/\s+/).filter(Boolean).join(' ')
  const q = norm(quote)
  const excerpt = excerpts.map(norm).find((e) => e.includes(q))
  if (!excerpt) return <bdi>״{quote}״</bdi>
  const at = excerpt.indexOf(q)
  return (
    <bdi className="block" data-testid="web-excerpt">
      {excerpt.slice(0, at)}
      <mark className="bg-amber-200 dark:bg-amber-800">{q}</mark>
      {excerpt.slice(at + q.length)}
    </bdi>
  )
}

const LABELS: Record<string, { text: string; className: string }> = {
  consistent: { text: 'עקבי', className: 'border-emerald-600/40 bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200' },
  tension: { text: 'מתח', className: 'border-amber-600/50 bg-amber-50 text-amber-900 dark:bg-amber-950 dark:text-amber-200' },
  unexplained: { text: 'לא מוסבר', className: 'border-slate-500/40 bg-slate-100 text-slate-800 dark:bg-slate-900 dark:text-slate-200' },
}

const UNITS: Record<string, string> = {
  money: 'סכום',
  percent: 'שיעור (שבר עשרוני)',
  pp: 'נקודות אחוז (שבר עשרוני)',
  multiple: 'מכפיל',
  count: 'כמות',
  per_share: 'למניה',
  number: 'מספר',
}

// derive operations (ratio definitions are already Hebrew and shown as they are)
const OPERATIONS: Record<string, string> = {
  pct_change: 'שינוי באחוזים בין שני נתונים',
  ratio: 'יחס בין שני נתונים',
  share: 'חלקו של נתון מתוך סך',
  sum: 'סכום נתונים',
  diff: 'הפרש בין שני נתונים',
}

/** Shift a decimal string two places right without floating point ("0.0824966" → "8.24966"). */
function timesHundred(value: string): string {
  const negative = value.startsWith('-')
  const [int, frac = ''] = value.replace('-', '').split('.')
  const padded = frac.padEnd(2, '0')
  const whole = (int + padded.slice(0, 2)).replace(/^0+(?=\d)/, '')
  const rest = padded.slice(2).replace(/0+$/, '')
  return `${negative ? '-' : ''}${whole}${rest ? `.${rest}` : ''}`
}

function exactValue(f: StoryFact): string {
  if (f.value == null) return `אין ערך${f.reason ? ` (${f.reason})` : ''}`
  if (f.unit === 'percent' || f.unit === 'pp') {
    const pct = timesHundred(f.value)
    const [whole, frac = ''] = pct.split('.')
    const shown = frac.length > 4 ? `${whole}.${frac.slice(0, 4)}…` : pct
    return f.unit === 'percent' ? `${shown}%` : `${shown} נקודות אחוז`
  }
  const grouped = groupDecimal(f.value)
  return f.unit === 'money' || f.unit === 'per_share' ? `${grouped} ${currencySymbol(f.currency)}`.trim() : grouped
}

/** A number in the story: the server's display string, with its provenance on hover or focus. */
function FactValue({ segment, facts, sources }: { segment: StorySegment; facts: Facts; sources: Sources }) {
  const tipId = useId()
  const fact = segment.fact_id ? facts.get(segment.fact_id) : undefined
  const low = fact?.confidence === 'low'
  const web = fact?.kind === 'WEB'
  const source = web && fact?.source_id ? sources[fact.source_id] : undefined
  const dataChecks = (fact?.failed_checks ?? []).filter((c) => c !== 'web_source')
  return (
    <span className="group relative inline-block">
      <button
        type="button"
        data-testid="fact-value"
        data-fact-id={segment.fact_id ?? undefined}
        aria-describedby={tipId}
        className={cn(
          'rounded px-0.5 font-semibold underline decoration-dotted underline-offset-4 focus-visible:outline-2 focus-visible:outline-offset-2',
          low && 'decoration-amber-600 decoration-wavy',
        )}
      >
        <bdi dir="ltr">{segment.display}</bdi>
        {web && (
          <span data-testid="press-number" className="text-muted-foreground ms-0.5 inline-flex items-center text-xs">
            <Newspaper className="size-3" aria-hidden />
            <span className="sr-only">מספר מהעיתונות</span>
          </span>
        )}
        {low && (
          <span data-testid="low-confidence" className="ms-0.5 text-amber-700" aria-label="ביטחון נמוך">
            ⚠
          </span>
        )}
      </button>
      <span
        id={tipId}
        role="tooltip"
        data-testid="fact-provenance"
        className="bg-popover text-popover-foreground invisible absolute start-0 top-full z-20 mt-1 w-72 rounded-md border p-3 text-xs font-normal shadow-md group-focus-within:visible group-hover:visible"
      >
        {fact ? (
          <span className="block space-y-1">
            <span className="block font-medium">{fact.name_he}</span>
            <span className="block">
              שנים: <bdi dir="ltr">{fact.years.join('–')}</bdi> · {UNITS[fact.unit] ?? fact.unit}
            </span>
            <span className="block">
              ערך מדויק: <bdi dir="ltr" title={fact.value ?? undefined}>{exactValue(fact)}</bdi>
            </span>
            {fact.operation && fact.kind !== 'TXT' && fact.kind !== 'WEB' && (
              <span className="block">חישוב: {OPERATIONS[fact.operation] ?? fact.operation}</span>
            )}
            {fact.inputs.length > 0 && (
              <span className="block">
                מקורות: <bdi dir="ltr" className="font-mono">{fact.inputs.join(', ')}</bdi>
              </span>
            )}
            {fact.quote && !web && (
              <span className="block">
                ציטוט: ״<bdi>{fact.quote}</bdi>״ <bdi dir="ltr" className="font-mono">({fact.paragraph_id})</bdi>
              </span>
            )}
            {web && (
              <span className="block space-y-1" data-testid="web-provenance">
                <span className="block font-medium">מספר מהעיתונות (מקור רשת)</span>
                {source && (
                  <span className="block">
                    מקור: <bdi>{source.title || source.url}</bdi> · <bdi dir="ltr">{source.published_at ?? UNKNOWN_DATE}</bdi>
                  </span>
                )}
                {fact.quote && (
                  <span className="block">
                    ציטוט מתוך הקטע: <QuotedExcerpt quote={fact.quote} excerpts={source?.excerpts ?? []} />
                  </span>
                )}
              </span>
            )}
            {fact.source_filing_id != null && (
              <span className="block">
                תיוק מקור: <bdi dir="ltr">{fact.source_filing_id}</bdi>
              </span>
            )}
            <span className={cn('block', low && 'text-amber-800 dark:text-amber-300')}>
              {!low && 'ביטחון גבוה'}
              {low && fact.failed_checks.includes('web_source') && 'ביטחון נמוך: מקור עיתונאי, לא מבוקר'}
              {low && dataChecks.length > 0 && (
                <span className="block">ביטחון נמוך: נכשלו בדיקות עקביות בנתוני הספק ({dataChecks.join(', ')})</span>
              )}
              {low && fact.failed_checks.length === 0 && 'ביטחון נמוך'}
            </span>
          </span>
        ) : (
          <span>{segment.fact_id}</span>
        )}
      </span>
    </span>
  )
}

function Segments({ segments, facts, sources }: { segments: StorySegment[]; facts: Facts; sources: Sources }) {
  const body = segments.filter((s) => s.type !== 'caveat')
  const caveats = segments.filter((s) => s.type === 'caveat')
  return (
    <>
      <p className="leading-8">
        {body.map((s, i) =>
          s.type === 'fact' ? (
            <FactValue key={i} segment={s} facts={facts} sources={sources} />
          ) : (
            <span key={i}>{s.text}</span>
          ),
        )}
      </p>
      {caveats.map((c, i) => (
        <p key={i} className="flex items-start gap-1.5 text-sm text-amber-800 dark:text-amber-300" data-testid="story-caveat">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden /> {c.text}
        </p>
      ))}
    </>
  )
}

function Citations({ ids, citations, ticker }: { ids: string[]; citations: Record<string, StoryCitation>; ticker: string }) {
  const known = ids.map((id) => citations[id]).filter(Boolean)
  if (!known.length) return null
  return (
    <ul className="flex flex-wrap gap-2 text-xs" aria-label="מקורות בדוח">
      {known.map((c) => (
        <li key={c.paragraph_id} className="bg-muted flex items-center gap-2 rounded-full px-2.5 py-1">
          <span>
            FY{c.fiscal_year} · {pageLabel(c.page_printed, c.page_index)}
          </span>
          {c.node_id && (
            <Link
              to={`/${ticker}/${c.fiscal_year}/report/${encodeURIComponent(c.node_id)}`}
              data-testid="citation-reader-link"
              className="inline-flex items-center gap-0.5 underline"
            >
              <BookOpen className="size-3" aria-hidden /> בקורא
            </Link>
          )}
        </li>
      ))}
    </ul>
  )
}

/** Web sources: marked with an icon and a text label (not colour alone), opening in a new tab. */
function WebCitations({ ids, sources }: { ids: string[]; sources: Sources }) {
  const known = ids.map((id) => sources[id]).filter(Boolean)
  if (!known.length) return null
  return (
    <ul className="flex flex-wrap gap-2 text-xs" aria-label="מקורות רשת">
      {known.map((s) => (
        <li key={s.source_id} className="flex items-center gap-1.5 rounded-full border border-dashed px-2.5 py-1">
          <Globe className="size-3" aria-hidden />
          <span className="font-medium">מקור רשת:</span>
          <a
            href={s.url}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="web-citation"
            className="max-w-56 truncate underline"
            title={s.title || s.url}
          >
            {s.title || s.url}
          </a>
          <bdi dir="ltr" className="text-muted-foreground" data-testid="web-citation-date">
            {s.published_at ?? UNKNOWN_DATE}
          </bdi>
        </li>
      ))}
    </ul>
  )
}

function StoryView({ run, ticker }: { run: StoryRun; ticker: string }) {
  const facts: Facts = new Map(run.facts.map((f) => [f.fact_id, f]))
  const sources: Sources = run.web_sources ?? {}
  const sections = [
    { id: 'what-it-does', title: 'מה החברה עושה', paragraphs: run.rendered.what_it_does },
    { id: 'what-changed', title: 'מה השתנה', paragraphs: run.rendered.what_changed },
  ]
  return (
    <div className="space-y-6">
      {sections.map((section) => (
        <section key={section.id} aria-labelledby={section.id} className="space-y-3">
          <h2 id={section.id} className="text-lg font-semibold">
            {section.title}
          </h2>
          {section.paragraphs.map((p, i) => (
            <div key={i} className="space-y-2">
              <Segments segments={p.segments} facts={facts} sources={sources} />
              <Citations ids={p.paragraph_ids} citations={run.citations} ticker={ticker} />
              <WebCitations ids={p.source_ids ?? []} sources={sources} />
            </div>
          ))}
        </section>
      ))}
      <section aria-labelledby="story-vs-numbers" className="space-y-3">
        <h2 id="story-vs-numbers" className="text-lg font-semibold">
          הסיפור מול המספרים
        </h2>
        {run.rendered.story_vs_numbers.map((f, i) => {
          const label = LABELS[f.label]
          return (
            <Card key={i} data-testid="story-finding">
              <CardContent className="space-y-2 pt-4">
                <Badge variant="outline" className={label.className} data-testid="finding-label">
                  {label.text}
                </Badge>
                <Segments segments={f.segments} facts={facts} sources={sources} />
                <Citations ids={f.paragraph_ids} citations={run.citations} ticker={ticker} />
                <WebCitations ids={f.source_ids ?? []} sources={sources} />
              </CardContent>
            </Card>
          )
        })}
      </section>
      {run.rendered.unchanged_sections.length > 0 && (
        <p className="text-muted-foreground text-sm" data-testid="unchanged-sections">
          ללא שינוי בשלוש השנים: {run.rendered.unchanged_sections.map((u) => u.title).join(' · ')}
        </p>
      )}
    </div>
  )
}

type GenStatus = 'idle' | 'running' | 'error'

/** Start a live story run and show its progress; disabled (with the reason) outside live mode. */
function GeneratePanel({ ticker, hasStory }: { ticker: string; hasStory: boolean }) {
  const { mode, liveAllowed } = useMode()
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<GenStatus>('idle')
  const [steps, setSteps] = useState<string[]>([])
  const [searchesLeft, setSearchesLeft] = useState<number | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const stream = useRef<SseStream | null>(null)
  const live = mode === 'live'

  function start() {
    setStatus('running')
    setSteps([])
    setSearchesLeft(null)
    setError(null)
    stream.current = postSse<StoryRun>(
      `/api/companies/${encodeURIComponent(ticker)}/story`,
      { mode: 'live' },
      {
        onEvent: (event, p) => {
          if (event !== 'progress') return
          const progress = p as StoryProgress
          setSteps((s) => [...s, progress.message])
          const left = (progress.data as { searches_left?: unknown } | null | undefined)?.searches_left
          if (typeof left === 'number') setSearchesLeft(left)
        },
        onDone: (run) => {
          queryClient.setQueryData(['story', ticker], run)
          setStatus('idle')
        },
        onError: (e) => {
          setError(e)
          setStatus('error')
        },
      },
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{hasStory ? 'יצירת סיפור מחדש' : 'יצירת סיפור'}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-muted-foreground">
          הסוכנים קוראים את שלושת הדוחות השנתיים האחרונים וכותבים סיפור מאומת. ההרצה עולה כסף (קריאות LLM).
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={start} disabled={!live || status === 'running'} data-testid="generate-button">
            <Sparkles aria-hidden /> {status === 'running' ? 'יוצר…' : 'צור סיפור'}
          </Button>
          {status === 'running' && (
            <Button variant="outline" size="sm" onClick={() => stream.current?.abort()}>
              <Square aria-hidden /> עצור תצוגה
            </Button>
          )}
        </div>
        {!live && (
          <p className="text-muted-foreground" data-testid="generate-disabled-reason">
            {liveAllowed
              ? 'יצירת סיפור דורשת מצב חי. העבירו את המצב ל"חי" בראש העמוד.'
              : 'השרת מוגדר למצב מטמון בלבד, ולכן אפשר רק להציג סיפור שמור.'}
          </p>
        )}
        {searchesLeft !== null && (
          <p className="text-muted-foreground text-xs" data-testid="searches-left">
            חיפושי רשת שנותרו לסיפור: <bdi dir="ltr">{searchesLeft}</bdi>
          </p>
        )}
        {steps.length > 0 && (
          <ol className="text-muted-foreground max-h-48 list-inside list-decimal space-y-0.5 overflow-y-auto text-xs" data-testid="progress-list" aria-live="polite">
            {steps.map((s, i) => (
              <li key={i} dir="auto">
                {s}
              </li>
            ))}
          </ol>
        )}
        {error && <ErrorState error={error} onRetry={live ? start : undefined} />}
      </CardContent>
    </Card>
  )
}

/** A company's story from its last three annual reports: what it does, what changed, and the numbers. */
export function StoryPage() {
  const { ticker = '' } = useParams()
  const { mode } = useMode()
  const story = useQuery({
    queryKey: ['story', ticker],
    queryFn: ({ signal }) => api.story(ticker, mode, signal),
    retry: false,
  })
  const notCached = story.error instanceof ApiError && story.error.code === 'not_cached'
  const run = story.data
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
      <section className="space-y-4" aria-labelledby="story-title">
        <div>
          <h1 id="story-title" className="text-xl font-semibold" data-testid="story-title">
            סיפור החברה
          </h1>
          {run && (
            <p className="text-muted-foreground text-sm" data-testid="story-years">
              שנים <bdi dir="ltr">FY{run.years[0]}–FY{run.years[run.years.length - 1]}</bdi> · נכון ל־
              <bdi dir="ltr">{run.as_of}</bdi> · נוצר {formatDate(run.created_at)} · עלות {formatUsd(run.usage.cost_usd)}
            </p>
          )}
        </div>
        {story.isPending && <Loading label="טוען סיפור…" />}
        {notCached && (
          <Empty title="אין עדיין סיפור לחברה הזו">
            <p className="text-sm">אפשר ליצור אחד במצב חי (בחלונית שבצד).</p>
          </Empty>
        )}
        {story.error && !notCached && <ErrorState error={story.error} onRetry={() => story.refetch()} />}
        {run && <StoryView run={run} ticker={ticker} />}
      </section>
      <aside className="space-y-4">
        <GeneratePanel ticker={ticker} hasStory={!!run} />
      </aside>
    </div>
  )
}
