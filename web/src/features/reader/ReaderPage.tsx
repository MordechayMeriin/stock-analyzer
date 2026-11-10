import { useQuery } from '@tanstack/react-query'
import { ExternalLink, MessageSquare } from 'lucide-react'
import { useEffect } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { api } from '@/api/client'
import { useMode } from '@/app/mode'
import { ParagraphList } from '@/components/ParagraphList'
import { Empty, QueryView } from '@/components/states'
import { StructureTree } from '@/components/StructureTree'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { rememberYear } from '@/lib/years'

/** Report reader: structure tree + the chosen node's paragraphs with page citations. */
export function ReaderPage() {
  const { ticker = '', fy = '', nodeId } = useParams()
  const year = Number(fy)
  const { mode } = useMode()
  const navigate = useNavigate()
  const structure = useQuery({
    queryKey: ['structure', ticker, year, mode],
    queryFn: ({ signal }) => api.structure(ticker, year, mode, signal),
  })
  const node = useQuery({
    queryKey: ['node', ticker, year, nodeId, mode],
    queryFn: ({ signal }) => api.node(ticker, year, nodeId!, mode, signal),
    enabled: Boolean(nodeId),
  })

  useEffect(() => rememberYear(ticker, year), [ticker, year])

  return (
    <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
      <aside className="lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto">
        <QueryView query={structure} loadingLabel="טוען את מבנה הדוח…">
          {(s) => (
            <div className="space-y-3">
              <div className="text-muted-foreground space-y-1 text-xs">
                <p>
                  דוח <bdi>FY{s.fiscal_year}</bdi> · <bdi>{s.page_count}</bdi> עמודים · תיק{' '}
                  <bdi className="font-mono">#{s.filing_id}</bdi>
                </p>
                {s.document_url && (
                  <a href={s.document_url} target="_blank" rel="noreferrer" className="text-primary inline-flex items-center gap-1 underline">
                    הדוח המקורי (PDF) <ExternalLink className="size-3" aria-hidden />
                  </a>
                )}
                {s.warnings.length > 0 && (
                  <details>
                    <summary className="cursor-pointer">
                      <Badge variant="warning">{s.warnings.length} אזהרות ניתוח</Badge>
                    </summary>
                    <ul className="mt-1 list-disc ps-4">
                      {s.warnings.map((w) => (
                        <li key={w} dir="auto">
                          {w}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
              <StructureTree structure={s} activeId={nodeId} onSelect={(n) => navigate(`/${ticker}/${year}/report/${n.node_id}`)} />
            </div>
          )}
        </QueryView>
      </aside>
      <section aria-live="polite" className="min-w-0">
        {!nodeId ? (
          <Empty title="בחרו פרק או סעיף מעץ הדוח">
            <span className="text-sm">למשל: דיון בגורמי סיכון</span>
          </Empty>
        ) : (
          <QueryView query={node} isEmpty={(d) => d.paragraphs.length === 0} loadingLabel="טוען את הסעיף…">
            {(d) => (
              <article className="space-y-4">
                <header className="flex flex-wrap items-start justify-between gap-3 border-b pb-3">
                  <div>
                    <h1 className="text-xl font-semibold" data-testid="node-title">
                      {d.node.number && d.node.kind !== 'chapter' && <><bdi className="text-muted-foreground font-mono">{d.node.number}</bdi> </>}
                      {d.node.title}
                    </h1>
                    <p className="text-muted-foreground text-sm">
                      עמודים{' '}
                      <bdi dir="ltr">
                        {d.node.printed_pages[0] ?? d.node.pages[0]}–{d.node.printed_pages[1] ?? d.node.pages[1]}
                      </bdi>{' '}
                      · <bdi>{d.paragraphs.length}</bdi> פסקאות
                    </p>
                  </div>
                  <Button asChild size="sm" variant="outline">
                    <Link to={`/${ticker}/${year}/playground?node=${encodeURIComponent(d.node.node_id)}`}>
                      <MessageSquare aria-hidden /> שאל על הסעיף
                    </Link>
                  </Button>
                </header>
                <ParagraphList paragraphs={d.paragraphs} />
              </article>
            )}
          </QueryView>
        )}
      </section>
    </div>
  )
}
