/**
 * Typed API client. Every type comes from `schema.d.ts`, generated from the server's
 * openapi.json (`npm run gen:api`); nothing here is hand-typed.
 */
import { apiBaseUrl } from './config'
import type { components } from './schema'

export type Schemas = components['schemas']
export type Mode = 'cached' | 'live'
export type Company = Schemas['CompanyOut']
export type AddCompanyInput = Schemas['AddCompanyIn']
export type CompanySearchHit = Schemas['CompanySearchHit']
export type Filings = Schemas['FilingsOut']
export type FiscalYearFilings = Schemas['FiscalYearFilings']
export type Structure = Schemas['StructureOut']
export type ReportNode = Schemas['NodeOut']
export type NodeParagraphs = Schemas['NodeParagraphsOut']
export type PageParagraphs = Schemas['PageParagraphsOut']
export type Paragraph = Schemas['ParagraphOut']
export type Financials = Schemas['FinancialsOut']
export type Ratios = Schemas['RatiosOut']
export type PeerBenchmark = Schemas['PeerBenchmarkOut']
export type PeerBenchmarkRun = Schemas['PeerBenchmarkRunOut']
export type RatioSeries = Schemas['RatioSeriesOut']
export type RatioValue = Schemas['RatioValueOut']
export type CheckResult = Schemas['CheckOut']
export type Usage = Schemas['UsageOut']
export type Health = Schemas['HealthOut']
export type ApiErrorBody = Schemas['ErrorOut']
export type PlaygroundRequest = Schemas['PlaygroundRequest']
export type PlaygroundDone = Schemas['PlaygroundDone']
export type StoryRun = Schemas['StoryRun']
export type StoryProgress = Schemas['StoryProgress']
export type StoryFact = Schemas['Fact']
export type StorySegment = Schemas['Segment']
export type StoryCitation = Schemas['Citation']
export type OsintResult = Schemas['ResearchResult']
export type OsintFinding = Schemas['KeptFinding']
export type OsintScorecard = Schemas['Scorecard']
export type OsintPoint = Schemas['Point']
export type OsintProgress = Schemas['OsintProgress']
export type OsintLabel = Schemas['AreaAssessment']['label']
export type OsintArea = Schemas['AreaAssessment']['area']
export type OsintTrend = Schemas['AreaAssessment']['trend']
export type OsintImportance = Schemas['AreaAssessment']['importance']
export type OsintDriver = Schemas['KeyDriver']

/** An API failure carrying the server's machine-readable code. */
export class ApiError extends Error {
  readonly code: string
  readonly status: number

  constructor(code: string, message: string, status: number) {
    super(message)
    this.code = code
    this.status = status
  }
}

type Query = Record<string, string | number | undefined | null>

export function url(path: string, query?: Query): string {
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(query ?? {})) if (v !== undefined && v !== null && v !== '') params.set(k, String(v))
  const qs = params.toString()
  return `${apiBaseUrl()}${path}${qs ? `?${qs}` : ''}`
}

export async function errorFrom(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as Partial<ApiErrorBody>
    if (body && typeof body.code === 'string') return new ApiError(body.code, body.message ?? res.statusText, res.status)
  } catch {
    /* not JSON */
  }
  return new ApiError('http_error', `${res.status} ${res.statusText}`, res.status)
}

/** One request with the shared error mapping. Resolves to undefined for 204 No Content. */
async function send<T>(
  method: 'GET' | 'POST' | 'DELETE',
  path: string,
  query?: Query,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  let res: Response
  try {
    res = await fetch(url(path, query), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError('network_error', 'השרת אינו זמין. בדקו שהשרת פועל ושכתובת ה-API נכונה.', 0)
  }
  if (!res.ok) throw await errorFrom(res)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

const get = <T>(path: string, query?: Query, signal?: AbortSignal) => send<T>('GET', path, query, undefined, signal)

const enc = encodeURIComponent

export const api = {
  health: (signal?: AbortSignal) => get<Health>('/health', undefined, signal),
  companies: (mode: Mode, signal?: AbortSignal) => get<Company[]>('/api/companies', { mode }, signal),
  searchCompanies: (q: string, mode: Mode, signal?: AbortSignal) =>
    get<CompanySearchHit[]>('/api/companies/search', { q, mode }, signal),
  /** Start tracking a company. Live mode only (the server refuses it in cached mode). */
  addCompany: (input: AddCompanyInput, mode: Mode) => send<Company>('POST', '/api/companies', { mode }, input),
  /** Stop tracking a runtime-added company. Live mode only. */
  removeCompany: (ticker: string, mode: Mode) => send<void>('DELETE', `/api/companies/${enc(ticker)}`, { mode }),
  company: (ticker: string, mode: Mode, signal?: AbortSignal) =>
    get<Company>(`/api/companies/${enc(ticker)}`, { mode }, signal),
  filings: (ticker: string, mode: Mode, signal?: AbortSignal) =>
    get<Filings>(`/api/companies/${enc(ticker)}/filings`, { mode }, signal),
  financials: (ticker: string, mode: Mode, asOf?: string, signal?: AbortSignal) =>
    get<Financials>(`/api/companies/${enc(ticker)}/financials`, { mode, as_of: asOf }, signal),
  ratios: (ticker: string, mode: Mode, asOf?: string, signal?: AbortSignal) =>
    get<Ratios>(`/api/companies/${enc(ticker)}/ratios`, { mode, as_of: asOf }, signal),
  /** Ratios beside curated or same-ISIC peers per market. Stored data only, in either mode. */
  peerBenchmark: (ticker: string, mode: Mode, signal?: AbortSignal) =>
    get<PeerBenchmark>(`/api/companies/${enc(ticker)}/peer-benchmark`, { mode }, signal),
  /** Live only: without confirm, the credit estimate; with confirm, fetch up to max_fetch financials. */
  runPeerBenchmark: (ticker: string, mode: Mode, confirm: boolean) =>
    send<PeerBenchmarkRun>('POST', `/api/companies/${enc(ticker)}/peer-benchmark`, { mode }, { confirm }),
  structure: (ticker: string, fy: number, mode: Mode, signal?: AbortSignal) =>
    get<Structure>(`/api/companies/${enc(ticker)}/reports/${fy}/structure`, { mode }, signal),
  node: (ticker: string, fy: number, nodeId: string, mode: Mode, signal?: AbortSignal) =>
    get<NodeParagraphs>(`/api/companies/${enc(ticker)}/reports/${fy}/nodes/${enc(nodeId)}`, { mode }, signal),
  page: (ticker: string, fy: number, page: number, mode: Mode, signal?: AbortSignal) =>
    get<PageParagraphs>(`/api/companies/${enc(ticker)}/reports/${fy}/pages/${page}`, { mode }, signal),
  usage: (mode: Mode, signal?: AbortSignal) => get<Usage>('/api/usage', { mode }, signal),
  story: (ticker: string, mode: Mode, signal?: AbortSignal) =>
    get<StoryRun>(`/api/companies/${enc(ticker)}/story`, { mode }, signal),
  /** Latest stored OSINT scorecard. Never searches, in either mode; 409 not_cached when never researched. */
  osint: (ticker: string, months: number, mode: Mode, signal?: AbortSignal) =>
    get<OsintResult>(`/api/companies/${enc(ticker)}/osint`, { mode, months }, signal),
  // A live run is streamed (progress, then the result): see OsintPage, which uses postSse.
}
