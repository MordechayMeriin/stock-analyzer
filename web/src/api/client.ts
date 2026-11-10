/**
 * Typed API client. Every type comes from `schema.d.ts`, generated from the server's
 * openapi.json (`npm run gen:api`); nothing here is hand-typed.
 */
import { apiBaseUrl } from './config'
import type { components } from './schema'

export type Schemas = components['schemas']
export type Mode = 'cached' | 'live'
export type Company = Schemas['CompanyOut']
export type CompanySearchHit = Schemas['CompanySearchHit']
export type Filings = Schemas['FilingsOut']
export type FiscalYearFilings = Schemas['FiscalYearFilings']
export type Structure = Schemas['StructureOut']
export type ReportNode = Schemas['NodeOut']
export type NodeParagraphs = Schemas['NodeParagraphsOut']
export type PageParagraphs = Schemas['PageParagraphsOut']
export type Paragraph = Schemas['ParagraphOut']
export type Financials = Schemas['FinancialsOut']
export type Usage = Schemas['UsageOut']
export type Health = Schemas['HealthOut']
export type ApiErrorBody = Schemas['ErrorOut']
export type PlaygroundRequest = Schemas['PlaygroundRequest']
export type PlaygroundDone = Schemas['PlaygroundDone']

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

async function get<T>(path: string, query?: Query, signal?: AbortSignal): Promise<T> {
  let res: Response
  try {
    res = await fetch(url(path, query), { headers: { Accept: 'application/json' }, signal })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError('network_error', 'השרת אינו זמין. בדקו שהשרת פועל ושכתובת ה-API נכונה.', 0)
  }
  if (!res.ok) throw await errorFrom(res)
  return (await res.json()) as T
}

const enc = encodeURIComponent

export const api = {
  health: (signal?: AbortSignal) => get<Health>('/health', undefined, signal),
  companies: (mode: Mode, signal?: AbortSignal) => get<Company[]>('/api/companies', { mode }, signal),
  searchCompanies: (q: string, mode: Mode, signal?: AbortSignal) =>
    get<CompanySearchHit[]>('/api/companies/search', { q, mode }, signal),
  company: (ticker: string, mode: Mode, signal?: AbortSignal) =>
    get<Company>(`/api/companies/${enc(ticker)}`, { mode }, signal),
  filings: (ticker: string, mode: Mode, signal?: AbortSignal) =>
    get<Filings>(`/api/companies/${enc(ticker)}/filings`, { mode }, signal),
  financials: (ticker: string, mode: Mode, asOf?: string, signal?: AbortSignal) =>
    get<Financials>(`/api/companies/${enc(ticker)}/financials`, { mode, as_of: asOf }, signal),
  structure: (ticker: string, fy: number, mode: Mode, signal?: AbortSignal) =>
    get<Structure>(`/api/companies/${enc(ticker)}/reports/${fy}/structure`, { mode }, signal),
  node: (ticker: string, fy: number, nodeId: string, mode: Mode, signal?: AbortSignal) =>
    get<NodeParagraphs>(`/api/companies/${enc(ticker)}/reports/${fy}/nodes/${enc(nodeId)}`, { mode }, signal),
  page: (ticker: string, fy: number, page: number, mode: Mode, signal?: AbortSignal) =>
    get<PageParagraphs>(`/api/companies/${enc(ticker)}/reports/${fy}/pages/${page}`, { mode }, signal),
  usage: (mode: Mode, signal?: AbortSignal) => get<Usage>('/api/usage', { mode }, signal),
}
