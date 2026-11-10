import { useQuery } from '@tanstack/react-query'
import { ExternalLink, Send, Square } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import { api, type ApiError, type PlaygroundDone, type PlaygroundRequest } from '@/api/client'
import { postSse, type SseStream } from '@/api/sse'
import { useMode } from '@/app/mode'
import { ErrorState, QueryView } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { formatUsd } from '@/lib/format'
import { rememberYear } from '@/lib/years'

type Status = 'idle' | 'streaming' | 'done' | 'cancelled' | 'error'

function pageOfPid(pid: string): number | null {
  const m = /-p(\d{4})-\d{3}$/.exec(pid)
  return m ? Number(m[1]) : null
}

/** Ask the main model about a selected section or pages; the Hebrew answer streams in. */
export function PlaygroundPage() {
  const { ticker = '', fy = '' } = useParams()
  const year = Number(fy)
  const [params] = useSearchParams()
  const { mode, liveAllowed, health } = useMode()
  const structure = useQuery({ queryKey: ['structure', ticker, year, mode], queryFn: ({ signal }) => api.structure(ticker, year, mode, signal) })

  const [selectionKind, setSelectionKind] = useState<'node' | 'pages'>('node')
  const [nodeId, setNodeId] = useState(params.get('node') ?? '')
  const [first, setFirst] = useState('')
  const [last, setLast] = useState('')
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [status, setStatus] = useState<Status>('idle')
  const [done, setDone] = useState<PlaygroundDone | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const stream = useRef<SseStream | null>(null)

  useEffect(() => rememberYear(ticker, year), [ticker, year])
  useEffect(() => () => stream.current?.abort(), [])

  const options = useMemo(
    () =>
      (structure.data?.nodes ?? []).map((n) => ({
        id: n.node_id,
        label: `${'  '.repeat(Math.max(n.level - 1, 0))}${n.number && n.kind !== 'chapter' ? `${n.number} ` : ''}${n.title}`,
      })),
    [structure.data],
  )
  const llmIsFake = health?.llm_fake ?? false
  const needsLive = !llmIsFake && mode !== 'live'

  const ask = (e: FormEvent) => {
    e.preventDefault()
    const body: PlaygroundRequest = {
      ticker,
      fiscal_year: year,
      question: question.trim(),
      mode,
      ...(selectionKind === 'node' ? { node_id: nodeId } : { pages: { first: Number(first), last: Number(last) } }),
    }
    setAnswer('')
    setDone(null)
    setError(null)
    setStatus('streaming')
    stream.current = postSse<PlaygroundDone>('/api/playground', body, {
      onDelta: (text) => setAnswer((a) => a + text),
      onDone: (d) => {
        setDone(d)
        setStatus('done')
      },
      onError: (err) => {
        setError(err)
        setStatus('error')
      },
    })
    stream.current.finished.then((outcome) => {
      if (outcome === 'aborted') setStatus('cancelled')
    })
  }

  const cancel = () => stream.current?.abort()
  const canAsk =
    question.trim().length > 0 &&
    status !== 'streaming' &&
    (selectionKind === 'node' ? Boolean(nodeId) : Number(first) >= 1 && Number(last) >= Number(first))

  return (
    <div className="grid gap-6 lg:grid-cols-[24rem_1fr]">
      <Card className="h-fit">
        <CardHeader>
          <CardTitle>שאלה על הדוח</CardTitle>
        </CardHeader>
        <CardContent>
          <QueryView query={structure} loadingLabel="טוען את מבנה הדוח…">
            {(s) => (
              <form onSubmit={ask} className="space-y-4">
                <fieldset className="space-y-2">
                  <legend className="text-sm font-medium">מה לשלוח למודל</legend>
                  <div className="flex gap-4 text-sm">
                    <label className="flex items-center gap-1.5">
                      <input type="radio" name="kind" checked={selectionKind === 'node'} onChange={() => setSelectionKind('node')} /> סעיף
                    </label>
                    <label className="flex items-center gap-1.5">
                      <input type="radio" name="kind" checked={selectionKind === 'pages'} onChange={() => setSelectionKind('pages')} /> טווח עמודים
                    </label>
                  </div>
                  {selectionKind === 'node' ? (
                    <select
                      aria-label="סעיף"
                      value={nodeId}
                      onChange={(e) => setNodeId(e.target.value)}
                      className="border-input w-full rounded-md border bg-transparent px-2 py-1.5 text-sm"
                    >
                      <option value="">בחרו סעיף…</option>
                      {options.map((o) => (
                        <option key={o.id} value={o.id}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <div className="flex items-center gap-2 text-sm">
                      מעמוד
                      <Input aria-label="מעמוד" type="number" min={1} max={s.page_count} value={first} onChange={(e) => setFirst(e.target.value)} className="w-20" dir="ltr" />
                      עד
                      <Input aria-label="עד עמוד" type="number" min={1} max={s.page_count} value={last} onChange={(e) => setLast(e.target.value)} className="w-20" dir="ltr" />
                      <span className="text-muted-foreground text-xs">(מתוך {s.page_count}, לפי עמודי הקובץ)</span>
                    </div>
                  )}
                </fieldset>
                <label className="block space-y-1.5 text-sm font-medium">
                  השאלה
                  <textarea
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    rows={4}
                    maxLength={2000}
                    placeholder="למשל: מהם גורמי הסיכון החדשים השנה?"
                    className="border-input w-full rounded-md border bg-transparent px-3 py-2 font-normal"
                  />
                </label>
                {needsLive && (
                  <p className="text-muted-foreground text-xs">
                    {liveAllowed ? 'שאלה למודל עולה כסף ולכן דורשת מצב חי.' : 'השרת במצב מטמון בלבד ואינו מאפשר קריאות בתשלום למודל.'}
                  </p>
                )}
                <div className="flex gap-2">
                  <Button type="submit" disabled={!canAsk || needsLive}>
                    <Send aria-hidden /> שליחה
                  </Button>
                  {status === 'streaming' && (
                    <Button type="button" variant="outline" onClick={cancel}>
                      <Square aria-hidden /> עצירה
                    </Button>
                  )}
                </div>
                {llmIsFake && <Badge variant="secondary">מודל מדומה (LLM_FAKE)</Badge>}
              </form>
            )}
          </QueryView>
        </CardContent>
      </Card>

      <section aria-live="polite" className="min-w-0 space-y-4">
        {status === 'idle' && <p className="text-muted-foreground">התשובה תופיע כאן.</p>}
        {(answer || status === 'streaming') && (
          <Card data-testid="answer" data-status={status}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                תשובה
                {status === 'streaming' && <Badge variant="secondary">מתקבלת…</Badge>}
                {status === 'cancelled' && <Badge variant="warning">בוטלה — תשובה חלקית</Badge>}
                {status === 'done' && <Badge variant="success">הושלמה</Badge>}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="leading-7 whitespace-pre-wrap" dir="rtl">
                {answer}
                {status === 'streaming' && <span className="animate-pulse">▍</span>}
              </p>
            </CardContent>
          </Card>
        )}
        {error && <ErrorState error={error} />}
        {done && (
          <Card data-testid="answer-meta">
            <CardContent className="space-y-3 text-sm">
              <p>
                עלות: <bdi dir="ltr" className="font-medium">{formatUsd(done.usage.cost)}</bdi> · טוקנים:{' '}
                <bdi>{done.usage.input_tokens}</bdi> קלט / <bdi>{done.usage.output_tokens}</bdi> פלט · מודל <bdi className="font-mono text-xs">{done.model}</bdi>{' '}
                · <bdi>{(done.latency_ms / 1000).toFixed(1)}</bdi> שניות
              </p>
              <div>
                <p className="mb-1 font-medium">הפסקאות שנשלחו למודל ({done.paragraph_ids.length})</p>
                <ul className="flex flex-wrap gap-1.5" data-testid="source-links">
                  {done.paragraph_ids.map((pid) => {
                    const href = done.citations[pid]
                    const page = pageOfPid(pid)
                    return (
                      <li key={pid}>
                        {href ? (
                          <a href={href} target="_blank" rel="noreferrer" className="hover:bg-accent inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-xs" title={`עמוד ${page} בקובץ`}>
                            <bdi>{pid}</bdi> <ExternalLink className="size-3" aria-hidden />
                          </a>
                        ) : (
                          <bdi className="font-mono text-xs">{pid}</bdi>
                        )}
                      </li>
                    )
                  })}
                </ul>
                {selectionKind === 'node' && nodeId && (
                  <Link className="text-primary mt-2 inline-block underline" to={`/${ticker}/${year}/report/${nodeId}`}>
                    לקריאת הסעיף בדוח
                  </Link>
                )}
              </div>
            </CardContent>
          </Card>
        )}
      </section>
    </div>
  )
}
