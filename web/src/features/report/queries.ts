import { useQuery } from '@tanstack/react-query'

import { api, ApiError, type Mode } from '@/api/client'
import { useMode } from '@/app/mode'

import axisDetails from './fixtures/mltm.axis-details.json'
import fullFixture from './fixtures/mltm.full.json'
import sparseFixture from './fixtures/mltm.sparse.json'
import type { AxisDetail, CompanyReport } from './types'

/** Reports served until the server endpoint exists, keyed by ticker. */
const FIXTURES: Record<string, CompanyReport> = {
  MLTM: fullFixture as CompanyReport,
  // Dev ticker for the edge-case fixture (missing axis data, stale report, no events).
  SPARSE: sparseFixture as CompanyReport,
}

/** Whether a report is known to exist without asking the server (a dev fixture). */
export function hasReport(ticker: string): boolean {
  return ticker.toUpperCase() in FIXTURES
}

/** The fixture tickers with their company, for search when the server is unreachable. */
export const FIXTURE_COMPANIES = Object.entries(FIXTURES).map(([ticker, r]) => ({
  ticker,
  name_he: ticker === r.company.ticker ? r.company.name_he : `${r.company.name_he} · נתוני בדיקה`,
  name_en: r.company.name_en ?? null,
}))

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
 * The one place the report is loaded. MLTM and SPARSE are dev fixtures; every other ticker comes
 * from `GET /api/companies/{ticker}/report?mode=` (409 `not_cached` until it is built in live mode).
 */
export async function fetchReport(ticker: string, mode: Mode, signal?: AbortSignal): Promise<CompanyReport> {
  const fixture = FIXTURES[ticker.toUpperCase()]
  if (fixture) {
    await wait(FIXTURE_DELAY_MS, signal)
    return fixture
  }
  // the server's models mirror types.ts; optional fields it cannot fill are left out, never null
  return (await api.report(ticker, mode, signal)) as unknown as CompanyReport
}

/** Whether an error means "no report built yet" (so the page can offer to build it). */
export function isNotCached(error: unknown): boolean {
  return error instanceof ApiError && error.code === 'not_cached'
}

export const reportQueryKey = (ticker: string, mode: Mode) => ['report', ticker.toUpperCase(), mode] as const

/** The full report (all years) for one company. Switching years never refetches. */
export function useReport(ticker: string) {
  const { mode } = useMode()
  return useQuery({
    queryKey: reportQueryKey(ticker, mode),
    queryFn: ({ signal }) => fetchReport(ticker, mode, signal),
    staleTime: 5 * 60_000,
    retry: (count, error) =>
      !(error instanceof ApiError && (error.status === 404 || error.code === 'not_cached')) && count < 2,
  })
}

/** Axis breakdowns served from fixtures, keyed `axisId:year`. */
const AXIS_DETAILS = axisDetails as Record<string, AxisDetail>

/**
 * The one place an axis breakdown is loaded (`GET .../report/axes/{axisId}?year=`): fixtures for
 * MLTM, the server for every other non-fixture ticker.
 */
export async function fetchAxisDetail(
  ticker: string,
  axisId: string,
  year: number,
  signal?: AbortSignal,
): Promise<AxisDetail> {
  const upper = ticker.toUpperCase()
  if (upper in FIXTURES) {
    await wait(FIXTURE_DELAY_MS, signal)
    const detail = upper === 'MLTM' ? AXIS_DETAILS[`${axisId}:${year}`] : undefined
    if (!detail) throw new ApiError('not_found', 'הפירוט אינו זמין לשנה זו', 404)
    return detail
  }
  return (await api.reportAxis(ticker, axisId, year, signal)) as unknown as AxisDetail
}

/** One axis's breakdown for one year. Loads only when `enabled` (the row is open), then is cached. */
export function useAxisDetail(ticker: string, axisId: string, year: number, enabled: boolean) {
  return useQuery({
    queryKey: ['axis-detail', ticker.toUpperCase(), axisId, year] as const,
    queryFn: ({ signal }) => fetchAxisDetail(ticker, axisId, year, signal),
    enabled,
    staleTime: Infinity,
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  })
}
