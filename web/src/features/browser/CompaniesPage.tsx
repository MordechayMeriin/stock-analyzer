import { useQuery } from '@tanstack/react-query'
import { Plus, Search } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { api } from '@/api/client'
import { useMode } from '@/app/mode'
import { QueryView } from '@/components/states'
import { UsagePanel } from '@/components/UsagePanel'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'

import { AddCompanyForm, RemoveCompanyButton } from './TrackCompany'
import { useTrackingGate } from './tracking'

/** Home: tracked companies, provider search and credit usage. */
export function CompaniesPage() {
  const { mode } = useMode()
  const companies = useQuery({ queryKey: ['companies', mode], queryFn: ({ signal }) => api.companies(mode, signal) })
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')
  const search = useQuery({
    queryKey: ['search', query, mode],
    queryFn: ({ signal }) => api.searchCompanies(query, mode, signal),
    enabled: query.length > 0,
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    setQuery(draft.trim())
    setAdding(null)
  }
  const gate = useTrackingGate()
  const [adding, setAdding] = useState<number | null>(null) // provider id whose add form is open

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
      <div className="space-y-6">
        <section aria-labelledby="tracked" className="space-y-3">
          <h1 id="tracked" className="text-xl font-semibold">
            חברות במעקב
          </h1>
          <QueryView query={companies} isEmpty={(d) => d.length === 0} loadingLabel="טוען חברות…">
            {(list) => (
              <ul className="grid gap-3 sm:grid-cols-2">
                {list.map((c) => (
                  <li key={c.ticker}>
                    <Link to={`/${c.ticker}`} className="block" data-testid={`company-${c.ticker}`}>
                      <Card className="hover:border-primary/50 transition-colors">
                        <CardHeader>
                          <CardTitle className="flex items-center justify-between gap-2">
                            <span>{c.name_he}</span>
                            <Badge variant="outline" className="font-mono">
                              <bdi>{c.ticker}</bdi>
                            </Badge>
                          </CardTitle>
                          {(c.name_en || c.isin) && (
                            <CardDescription>
                              {c.name_en && <bdi dir="ltr">{c.name_en}</bdi>}
                              {c.name_en && c.isin && ' · '}
                              {c.isin && (
                                <>
                                  ISIN <bdi className="font-mono">{c.isin}</bdi>
                                </>
                              )}
                            </CardDescription>
                          )}
                        </CardHeader>
                      </Card>
                    </Link>
                    <RemoveCompanyButton company={c} />
                  </li>
                ))}
              </ul>
            )}
          </QueryView>
        </section>

        <section aria-labelledby="search" className="space-y-3">
          <h2 id="search" className="text-lg font-semibold">
            חיפוש חברה אצל ספק הדוחות
          </h2>
          <form onSubmit={submit} className="flex max-w-lg gap-2" role="search">
            <Input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="שם חברה או סימול, למשל מלם"
              aria-label="חיפוש חברה"
            />
            <Button type="submit" disabled={!draft.trim()}>
              <Search aria-hidden /> חיפוש
            </Button>
          </form>
          {query && !gate.enabled && (
            <p id="tracking-gate" className="text-muted-foreground text-xs" data-testid="tracking-gate">
              {gate.reason}
            </p>
          )}
          {query && (
            <QueryView query={search} isEmpty={(d) => d.length === 0} loadingLabel="מחפש…">
              {(hits) => (
                <ul className="divide-y rounded-lg border">
                  {hits.map((h) => (
                    <li key={h.fr_company_id} data-testid={`hit-${h.fr_company_id}`}>
                      <div className="flex items-center justify-between gap-3 px-4 py-2 text-sm">
                        <span>
                          <bdi>{h.name}</bdi>{' '}
                          {h.ticker && <bdi className="text-muted-foreground font-mono text-xs">{h.ticker}</bdi>}
                        </span>
                        {h.tracked_ticker ? (
                          <Link className="text-primary underline" to={`/${h.tracked_ticker}`}>
                            פתח
                          </Link>
                        ) : (
                          <span className="flex items-center gap-2">
                            <span className="text-muted-foreground text-xs">לא במעקב</span>
                            {adding !== h.fr_company_id && (
                              <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                className="h-7"
                                disabled={!gate.enabled}
                                aria-describedby={gate.enabled ? undefined : 'tracking-gate'}
                                onClick={() => setAdding(h.fr_company_id)}
                              >
                                <Plus aria-hidden /> הוסף למעקב
                              </Button>
                            )}
                          </span>
                        )}
                      </div>
                      {adding === h.fr_company_id && !h.tracked_ticker && (
                        <AddCompanyForm hit={h} onDone={() => setAdding(null)} />
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </QueryView>
          )}
        </section>
      </div>
      <aside className="space-y-4">
        <UsagePanel />
      </aside>
    </div>
  )
}
