import { useQuery } from '@tanstack/react-query'
import { ExternalLink, FileText, MessageSquare, Table2 } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'

import { api, type FiscalYearFilings } from '@/api/client'
import { useMode } from '@/app/mode'
import { QueryView } from '@/components/states'
import { UsagePanel } from '@/components/UsagePanel'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatBytes, formatDate } from '@/lib/format'

function YearCard({ ticker, year }: { ticker: string; year: FiscalYearFilings }) {
  const selected = year.filings.find((f) => f.selected)
  return (
    <Card data-testid={`year-${year.fiscal_year}`}>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <span>
            שנת הדיווח <bdi>{year.fiscal_year}</bdi>
          </span>
          {year.report_cached ? (
            <Badge variant="success" data-testid="cached-badge">
              שמור במטמון
            </Badge>
          ) : (
            <Badge variant="warning" data-testid="not-cached-badge">
              לא שמור
            </Badge>
          )}
          {year.selection_error && <Badge variant="destructive">אין דוח מלא</Badge>}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <ul className="space-y-1.5 text-sm">
          {year.filings.map((f) => (
            <li key={f.filing_id} className="flex flex-wrap items-center gap-2" data-selected={f.selected}>
              {f.selected ? (
                <Badge data-testid="selected-badge">הדוח המלא</Badge>
              ) : (
                <Badge variant="outline">נלווה</Badge>
              )}
              <bdi dir="auto" className={f.selected ? 'font-medium' : 'text-muted-foreground'}>
                {f.title}
              </bdi>
              <span className="text-muted-foreground text-xs">
                <bdi className="font-mono">#{f.filing_id}</bdi> · <bdi>{f.file_extension}</bdi> ·{' '}
                <bdi>{formatBytes(f.file_size)}</bdi> · <bdi>{formatDate(f.release_datetime)}</bdi>
              </span>
              {f.document_url && (
                <a href={f.document_url} target="_blank" rel="noreferrer" className="text-primary inline-flex items-center gap-0.5 text-xs underline">
                  מסמך <ExternalLink className="size-3" aria-hidden />
                </a>
              )}
            </li>
          ))}
        </ul>
        {year.selection_error && <p className="text-destructive text-sm">{year.selection_error}</p>}
        {selected && (
          <div className="flex flex-wrap gap-2">
            <Button asChild size="sm">
              <Link to={`/${ticker}/${year.fiscal_year}/report`}>
                <FileText aria-hidden /> קריאת הדוח
              </Link>
            </Button>
            <Button asChild size="sm" variant="outline">
              <Link to={`/${ticker}/${year.fiscal_year}/playground`}>
                <MessageSquare aria-hidden /> שאלה ל-LLM
              </Link>
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/** A company's annual filings by fiscal year, the selected full report and cached status. */
export function CompanyPage() {
  const { ticker = '' } = useParams()
  const { mode } = useMode()
  const filings = useQuery({ queryKey: ['filings', ticker, mode], queryFn: ({ signal }) => api.filings(ticker, mode, signal) })
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
      <section className="space-y-4" aria-labelledby="filings-title">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h1 id="filings-title" className="text-xl font-semibold">
            דוחות שנתיים
          </h1>
          <Button asChild variant="outline" size="sm">
            <Link to={`/${ticker}/financials`}>
              <Table2 aria-hidden /> נתונים כספיים
            </Link>
          </Button>
        </div>
        <QueryView query={filings} isEmpty={(d) => d.years.length === 0} loadingLabel="טוען דוחות…">
          {(data) => (
            <div className="space-y-4">
              {data.years.map((y) => (
                <YearCard key={y.fiscal_year} ticker={data.ticker} year={y} />
              ))}
            </div>
          )}
        </QueryView>
      </section>
      <aside className="space-y-4">
        <UsagePanel />
      </aside>
    </div>
  )
}
