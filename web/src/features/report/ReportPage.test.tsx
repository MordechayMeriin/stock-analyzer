// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { KeyMetrics } from './components/KeyMetrics'
import { ReportPage } from './ReportPage'
import type { KeyMetric } from './types'

vi.mock('@/app/mode', () => ({ useMode: () => ({ mode: 'cached' }) }))

/** The server answers 404 for NOPE; anything else is "offline", so the fixtures are served. */
function stubServer() {
  vi.stubGlobal('fetch', async (input: RequestInfo | URL) =>
    String(input).includes('/NOPE/')
      ? new Response(JSON.stringify({ code: 'not_found', message: 'unknown ticker' }), { status: 404 })
      : Promise.reject(new TypeError('offline')),
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/c/:ticker" element={<ReportPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ReportPage with MLTM', () => {
  it('shows a skeleton, then the header, five rows and the radar', async () => {
    renderAt('/c/MLTM')
    expect(screen.getByRole('status')).toBeTruthy()
    expect(await screen.findByRole('heading', { name: 'מלם תים' })).toBeTruthy()
    expect(screen.getByRole('img')).toBeTruthy()
    expect(screen.getAllByRole('button', { expanded: false })).toHaveLength(5)
    expect(screen.getByText('נתח מניה חדשה').closest('a')?.getAttribute('href')).toBe('/c')
    expect(screen.getByText(/ואינם המלצה/)).toBeTruthy()
  })

  it('selects the year from ?y=', async () => {
    renderAt('/c/MLTM?y=2023')
    await screen.findByRole('heading', { name: 'מלם תים' })
    expect(screen.getByRole('tab', { name: '2023' }).getAttribute('aria-selected')).toBe('true')
    expect(screen.getByRole('img').getAttribute('aria-label')).toContain('יציבות 6 מתוך 10')
  })

  it('opens a row to show its detail and toggles aria-expanded', async () => {
    renderAt('/c/MLTM')
    await screen.findByRole('heading', { name: 'מלם תים' })
    const row = screen.getByRole('button', { name: /צמיחה/ })
    fireEvent.click(row)
    expect(row.getAttribute('aria-expanded')).toBe('true')
    expect(await screen.findByText('צמיחה בהכנסות של 12% בשנה')).toBeTruthy()
    expect(screen.getByText(/מעל לחציון הסקטור \(6\)/)).toBeTruthy()
    fireEvent.click(row)
    expect(row.getAttribute('aria-expanded')).toBe('false')
    fireEvent.click(row)
    expect(screen.getByText('צמיחה בהכנסות של 12% בשנה')).toBeTruthy()
  })

  it('shows important events first and reveals the rest on "הצג הכל"', async () => {
    renderAt('/c/MLTM')
    await screen.findByRole('heading', { name: 'מלם תים' })
    expect(screen.getByText('עדכון תחזית כלפי מעלה')).toBeTruthy()
    expect(screen.queryByText('מינוי מנכ״ל חדש')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'הצג הכל' }))
    expect(screen.getByText('מינוי מנכ״ל חדש')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'הצג הכל' })).toBeNull()
  })
})

describe('ReportPage edge states', () => {
  it('SPARSE: no radar, no-data row, an empty events note, stale line', async () => {
    renderAt('/c/SPARSE')
    await screen.findByRole('heading', { name: 'מלם תים' })
    expect(screen.queryByRole('img')).toBeNull()
    expect(screen.getByText('אין מספיק נתונים')).toBeTruthy()
    expect(screen.getByRole('heading', { name: /אירועים/ })).toBeTruthy()
    expect(screen.getByTestId('events-empty').textContent).toContain('עדיין לא נאספו אירועים')
    expect(screen.getByText(/נכון ל-/)).toBeTruthy()
    expect(within(screen.getByText('חוב נטו').closest('li')!).queryByTestId('metric-change')).toBeNull()
  })

  it('unknown ticker: not found message with a link back', async () => {
    stubServer()
    renderAt('/c/NOPE')
    expect(await screen.findByText('לא מצאנו את הטיקר')).toBeTruthy()
    expect(screen.getByText('נתח מניה חדשה')).toBeTruthy()
  })
})

describe('KeyMetrics', () => {
  it('shows a dash for a missing value', () => {
    const m: KeyMetric = {
      id: 'x',
      label: 'מדד',
      format: 'currency',
      currency: 'ILS',
      series: [{ fiscal_year: 2025, value: null }],
      change: null,
    }
    render(<KeyMetrics metrics={[m]} />)
    expect(screen.getByText('—')).toBeTruthy()
  })
})

describe('multi-year view', () => {
  it('?y=all selects the "3 שנים" tab and plays the years from the oldest', async () => {
    renderAt('/c/MLTM?y=all')
    expect((await screen.findByRole('tab', { name: '3 שנים' })).getAttribute('aria-selected')).toBe('true')
    expect(screen.getByTestId('rotating-radar')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'הצגת 2023' }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByRole('img').getAttribute('aria-label')).toContain('צמיחה 5 מתוך 10')
  })

  it('clicking a year tab leaves the multi-year view', async () => {
    renderAt('/c/MLTM?y=all')
    fireEvent.click(await screen.findByRole('tab', { name: '2024' }))
    expect(screen.queryByTestId('rotating-radar')).toBeNull()
  })
})
