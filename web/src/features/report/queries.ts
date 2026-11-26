import { useQuery } from '@tanstack/react-query'

import { ApiError, type Mode } from '@/api/client'
import { useMode } from '@/app/mode'

import fullFixture from './fixtures/mltm.full.json'
import type { CompanyReport } from './types'

/** Reports served until the server endpoint exists, keyed by ticker. */
const FIXTURES: Record<string, CompanyReport> = {
  MLTM: fullFixture as CompanyReport,
}

const FIXTURE_DELAY_MS = 300

function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException('Aborted', 'AbortError'))
    const timer = setTimeout(resolve, ms)
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(timer)
        reject(new DOMException('Aborted', 'AbortError'))
      },
      { once: true },
    )
  })
}

/**
 * The one place the report is loaded. For now it serves a fixture after a short delay; when the
 * server ships `GET /api/companies/{ticker}/report?mode=` (with SSE while processing), replace the
 * body with an `api.report(...)` call and leave every caller as it is.
 */
export async function fetchReport(ticker: string, mode: Mode, signal?: AbortSignal): Promise<CompanyReport> {
  void mode // the real endpoint takes it; fixtures are the same in both modes
  await wait(FIXTURE_DELAY_MS, signal)
  const report = FIXTURES[ticker.toUpperCase()]
  if (!report) throw new ApiError('not_found', `לא מצאנו את הטיקר ${ticker}`, 404)
  return report
}

export const reportQueryKey = (ticker: string, mode: Mode) => ['report', ticker.toUpperCase(), mode] as const

/** The full report (all years) for one company. Switching years never refetches. */
export function useReport(ticker: string) {
  const { mode } = useMode()
  return useQuery({
    queryKey: reportQueryKey(ticker, mode),
    queryFn: ({ signal }) => fetchReport(ticker, mode, signal),
    staleTime: 5 * 60_000,
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  })
}
