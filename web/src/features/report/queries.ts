import { useQuery } from '@tanstack/react-query'

import { api, ApiError, type Mode } from '@/api/client'
import { useMode } from '@/app/mode'

import axisDetails from './fixtures/mltm.axis-details.json'
import fullFixture from './fixtures/mltm.full.json'
import sparseFixture from './fixtures/mltm.sparse.json'
import type { AxisDetail, CompanyReport } from './types'

/** Offline fallbacks, keyed by ticker: served when the server is unreachable (and in tests). */
const FIXTURES: Record<string, CompanyReport> = {
  MLTM: fullFixture as CompanyReport,
  // Dev ticker for the edge-case fixture (missing axis data, stale report, no events).
  SPARSE: sparseFixture as CompanyReport,
}

const isOffline = (e: unknown) => e instanceof ApiError && e.code === 'network_error'

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
 * The one place the report is loaded: `GET /api/companies/{ticker}/report?mode=`. SPARSE is a
 * dev-only fixture; MLTM falls back to its fixture when the server is unreachable (demo offline).
 */
export async function fetchReport(ticker: string, mode: Mode, signal?: AbortSignal): Promise<CompanyReport> {
  const key = ticker.toUpperCase()
  if (key === 'SPARSE') return fixtureReport(key, signal)
  try {
    return (await api.report(key, mode, signal)) as CompanyReport
  } catch (e) {
    if (isOffline(e) && key in FIXTURES) return fixtureReport(key, signal)
    throw e
  }
}

async function fixtureReport(key: string, signal?: AbortSignal): Promise<CompanyReport> {
  await wait(FIXTURE_DELAY_MS, signal)
  const report = FIXTURES[key]
  if (!report) throw new ApiError('not_found', `לא מצאנו את הטיקר ${key}`, 404)
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

/** Axis breakdowns served from fixtures, keyed `axisId:year`. */
const AXIS_DETAILS = axisDetails as Record<string, AxisDetail>

/** The one place an axis breakdown is loaded (`GET .../report/axes/{axisId}?year=`), same fallback rules. */
export async function fetchAxisDetail(
  ticker: string,
  axisId: string,
  year: number,
  signal?: AbortSignal,
): Promise<AxisDetail> {
  const key = ticker.toUpperCase()
  if (key !== 'SPARSE') {
    try {
      return (await api.axisDetail(key, axisId, year, signal)) as AxisDetail
    } catch (e) {
      if (!isOffline(e)) throw e
    }
  }
  await wait(FIXTURE_DELAY_MS, signal)
  const detail = key === 'MLTM' ? AXIS_DETAILS[`${axisId}:${year}`] : undefined
  if (!detail) throw new ApiError('not_found', 'הפירוט אינו זמין לשנה זו', 404)
  return detail
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
