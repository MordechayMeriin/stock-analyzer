// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useParams } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api, type Company, type TickerSearch } from '@/api/client'

import { matchCompanies, mergeEntries, type SearchEntry } from './match'
import { SearchPage } from './SearchPage'

vi.mock('@/app/mode', () => ({ useMode: () => ({ mode: 'cached' }) }))
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return { ...actual, api: { ...actual.api, companies: vi.fn(), tickers: vi.fn() } }
})

const entry = (ticker: string, name_he: string, name_en: string | null, hasReport = false): SearchEntry => ({
  ticker,
  name_he,
  name_en,
  hasReport,
})

describe('matchCompanies', () => {
  const list = [
    entry('MLTM', 'מלם תים', 'Malam-Team Ltd.', true),
    entry('MLSR', 'מליסרון', 'Melisron', false),
    entry('LUMI', 'בנק לאומי', 'Bank Leumi', false),
    entry('TEVA', 'טבע', 'Teva Pharmaceutical', false),
  ]

  it('needs two characters', () => {
    expect(matchCompanies(list, 'm')).toEqual([])
  })

  it('matches ticker prefix, case-insensitively, report-ready first', () => {
    expect(matchCompanies(list, 'ml').map((e) => e.ticker)).toEqual(['MLTM', 'MLSR'])
  })

  it('matches Hebrew and English names, including a later word', () => {
    expect(matchCompanies(list, 'לאומי').map((e) => e.ticker)).toEqual(['LUMI'])
    expect(matchCompanies(list, 'pharma').map((e) => e.ticker)).toEqual(['TEVA'])
  })

  it('returns nothing for no match', () => {
    expect(matchCompanies(list, 'zzz')).toEqual([])
  })

  it('merges by ticker and keeps hasReport', () => {
    const merged = mergeEntries([entry('MLTM', 'מלם תים', null, true)], [entry('mltm', 'Malam', null, false), list[1]])
    expect(merged).toHaveLength(2)
    expect(merged[0].hasReport).toBe(true)
  })
})

function ReportStub() {
  return <p>report {useParams().ticker}</p>
}

function renderSearch() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/c']}>
        <Routes>
          <Route path="/c" element={<SearchPage />} />
          <Route path="/c/:ticker" element={<ReportStub />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SearchPage', () => {
  afterEach(cleanup)
  beforeEach(() => {
    vi.mocked(api.companies).mockResolvedValue([
      { ticker: 'LUMI', name_he: 'בנק לאומי', name_en: 'Bank Leumi' } as Company,
    ])
    // Default: the ticker directory is unreachable, so search falls back to local matching.
    vi.mocked(api.tickers).mockRejectedValue(new Error('down'))
  })

  it('suggests tracked and fixture companies and opens the chosen one with Enter', async () => {
    renderSearch()
    const input = screen.getByRole('combobox')
    fireEvent.change(input, { target: { value: 'בנק' } })
    expect(await screen.findByText('בנק לאומי')).toBeTruthy()
    expect(screen.queryByText('אין דוח עדיין')).toBeNull() // tracked companies have a report

    fireEvent.change(input, { target: { value: 'מלם' } })
    const options = screen.getAllByRole('option')
    expect(options[0].getAttribute('aria-selected')).toBe('true')
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(await screen.findByText('report MLTM')).toBeTruthy()
  })

  it('moves with the arrow keys and clears with Escape', async () => {
    renderSearch()
    const input = screen.getByRole('combobox') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'מלם' } }) // MLTM and the SPARSE fixture
    expect(screen.getAllByRole('option')).toHaveLength(2)
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    expect(screen.getAllByRole('option')[1].getAttribute('aria-selected')).toBe('true')
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(input.value).toBe('')
    expect(screen.queryByRole('listbox')).toBeNull()
  })

  it('says so when nothing matches', () => {
    renderSearch()
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'zzz' } })
    expect(screen.getByText('לא מצאנו חברה בשם הזה')).toBeTruthy()
  })

  it('still finds the fixtures when the server is down', async () => {
    vi.mocked(api.companies).mockRejectedValue(new Error('down'))
    renderSearch()
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'ml' } })
    fireEvent.click(await screen.findByText('MLTM'))
    expect(await screen.findByText('report MLTM')).toBeTruthy()
  })

  it('lists every company from the ticker directory; only tracked ones open', async () => {
    vi.mocked(api.tickers).mockResolvedValue({
      results: [
        { ticker: 'TEVA', name_he: 'טבע', name_en: 'Teva', fr_company_id: 1, isin: null, tracked: false },
        { ticker: 'TSEM', name_he: 'טאואר', name_en: 'Tower', fr_company_id: 2, isin: null, tracked: true },
      ],
      directory: { size: 2, fetched_at: null, source: 'directory' },
    } as TickerSearch)
    renderSearch()
    const input = screen.getByRole('combobox')
    fireEvent.change(input, { target: { value: 'te' } })
    const teva = (await screen.findByText('טבע')).closest('li')!
    expect(teva.getAttribute('aria-disabled')).toBe('true')
    expect(teva.textContent).toContain('אין דוח עדיין')
    fireEvent.click(teva)
    expect(screen.queryByText(/^report /)).toBeNull()

    fireEvent.click(screen.getByText('טאואר'))
    expect(await screen.findByText('report TSEM')).toBeTruthy()
  })
})
