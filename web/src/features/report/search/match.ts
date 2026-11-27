/** Pure search over a small company list (no provider calls: provider searches cost credits). */

export interface SearchEntry {
  ticker: string
  name_he: string
  name_en: string | null
  /** A report can be opened for it now. */
  hasReport: boolean
}

export const MIN_QUERY = 2
export const MAX_RESULTS = 8

/** Merge lists by ticker; the first occurrence wins, except that `hasReport` is OR-ed. */
export function mergeEntries(...lists: SearchEntry[][]): SearchEntry[] {
  const byTicker = new Map<string, SearchEntry>()
  for (const e of lists.flat()) {
    const key = e.ticker.toUpperCase()
    const seen = byTicker.get(key)
    byTicker.set(key, seen ? { ...seen, hasReport: seen.hasReport || e.hasReport } : e)
  }
  return [...byTicker.values()]
}

const norm = (s: string) => s.toLocaleLowerCase('en').replace(/["'״׳]/g, '').trim()

/**
 * Matches by ticker prefix, or by a word in the Hebrew or English name. Ranking: has a report
 * first, then exact ticker, ticker prefix, name prefix, any name match; ties by ticker.
 */
export function matchCompanies(entries: SearchEntry[], query: string): SearchEntry[] {
  const q = norm(query)
  if (q.length < MIN_QUERY) return []
  const scored: { e: SearchEntry; rank: number }[] = []
  for (const e of entries) {
    const t = norm(e.ticker)
    const names = [e.name_he, e.name_en ?? ''].map(norm)
    let rank: number
    if (t === q) rank = 0
    else if (t.startsWith(q)) rank = 1
    else if (names.some((n) => n.startsWith(q))) rank = 2
    else if (names.some((n) => n.split(/[\s\-–.,]+/).some((w) => w.startsWith(q)) || n.includes(q))) rank = 3
    else continue
    scored.push({ e, rank: rank + (e.hasReport ? 0 : 10) })
  }
  return scored
    .sort((a, b) => a.rank - b.rank || a.e.ticker.localeCompare(b.e.ticker))
    .slice(0, MAX_RESULTS)
    .map((s) => s.e)
}
