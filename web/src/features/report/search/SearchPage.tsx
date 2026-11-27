import { useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { useId, useMemo, useState, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '@/api/client'
import { useMode } from '@/app/mode'
import { cn } from '@/lib/utils'

import { FIXTURE_COMPANIES } from '../queries'
import { matchCompanies, mergeEntries, MIN_QUERY, type SearchEntry } from './match'

const FIXTURE_ENTRIES: SearchEntry[] = FIXTURE_COMPANIES.map((c) => ({ ...c, hasReport: true }))

/** Search (/c): one field, suggestions under it, Enter or click opens /c/:ticker. */
export function SearchPage() {
  const { mode } = useMode()
  const navigate = useNavigate()
  const listId = useId()
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)

  // Tracked companies come from the store: free. Search never calls the paid provider.
  const tracked = useQuery({
    queryKey: ['companies', mode],
    queryFn: ({ signal }) => api.companies(mode, signal),
    staleTime: 5 * 60_000,
  })
  const entries = useMemo(
    () =>
      mergeEntries(
        FIXTURE_ENTRIES,
        (tracked.data ?? []).map((c) => ({
          ticker: c.ticker,
          name_he: c.name_he,
          name_en: c.name_en ?? null,
          hasReport: true, // the server builds a report for every tracked company
        })),
      ),
    [tracked.data],
  )
  const results = useMemo(() => matchCompanies(entries, query), [entries, query])
  const open = query.trim().length >= MIN_QUERY
  const current = Math.min(active, Math.max(results.length - 1, 0))

  const choose = (e: SearchEntry) => navigate(`/c/${encodeURIComponent(e.ticker)}`)

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown' && results.length) {
      e.preventDefault()
      setActive((current + 1) % results.length)
    } else if (e.key === 'ArrowUp' && results.length) {
      e.preventDefault()
      setActive((current - 1 + results.length) % results.length)
    } else if (e.key === 'Enter' && results[current]) {
      e.preventDefault()
      choose(results[current])
    } else if (e.key === 'Escape') {
      setQuery('')
      setActive(0)
    }
  }

  return (
    <div className="mx-auto max-w-[480px] space-y-4 px-5 py-8">
      <h1 className="text-xl font-bold">ניתוח מניה</h1>
      <div className="relative">
        <Search aria-hidden="true" className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <input
          // eslint-disable-next-line jsx-a11y/no-autofocus -- the spec: back to search with the keyboard open
          autoFocus
          type="search"
          role="combobox"
          aria-label="חיפוש חברה לפי שם או טיקר"
          aria-expanded={open && results.length > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && results[current] ? `${listId}-${current}` : undefined}
          placeholder="שם חברה או טיקר"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setActive(0)
          }}
          onKeyDown={onKeyDown}
          className="h-12 w-full rounded-md border border-input bg-background ps-9 pe-3 text-base outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
      </div>

      {open && (
        <ul id={listId} role="listbox" aria-label="תוצאות" className="divide-y divide-border">
          {results.map((r, i) => (
            <li
              key={r.ticker}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === current}
              onMouseEnter={() => setActive(i)}
              onClick={() => choose(r)}
              className={cn(
                'flex min-h-[54px] cursor-pointer items-center justify-between gap-3 px-2',
                i === current && 'bg-muted',
              )}
            >
              <span className="min-w-0">
                <span className="block truncate font-medium">{r.name_he}</span>
                {r.name_en && (
                  <span dir="ltr" className="block truncate text-start text-[13px] text-muted-foreground">
                    {r.name_en}
                  </span>
                )}
              </span>
              <span className="flex shrink-0 items-center gap-2">
                {!r.hasReport && <span className="text-xs text-muted-foreground">אין דוח עדיין</span>}
                <bdi dir="ltr" className="font-mono text-sm">
                  {r.ticker}
                </bdi>
              </span>
            </li>
          ))}
          {results.length === 0 && <li className="py-3 text-sm text-muted-foreground">לא מצאנו חברה בשם הזה</li>}
        </ul>
      )}
    </div>
  )
}
