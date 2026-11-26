// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import full from '../fixtures/mltm.full.json'
import sparse from '../fixtures/mltm.sparse.json'
import type { CompanyReport } from '../types'
import { radarAxesForYear } from '../view'
import type { RadarAxis } from './geometry'
import { RadarChart } from './RadarChart'
import { RadarDevPage } from './RadarDevPage'

afterEach(cleanup)

describe('RadarChart with the full fixture', () => {
  it('draws five labelled axes with values, arrows colored by tone, and a polygon', () => {
    const { container } = render(<RadarChart axes={radarAxesForYear(full as CompanyReport, 2025)} />)
    const img = screen.getByRole('img')
    expect(img.getAttribute('aria-label')).toContain('יציבות 7 מתוך 10')
    expect(container.querySelectorAll('[data-testid^="label-"]')).toHaveLength(5)
    expect(screen.getByTestId('radar-polygon')).toBeTruthy()

    const safety = screen.getByTestId('arrow-safety')
    expect(safety.textContent).toBe('▼')
    expect(safety.getAttribute('fill')).toBe('#b91c1c')
    expect(screen.getByTestId('arrow-growth').getAttribute('fill')).toBe('#15803d')
    expect(screen.getByTestId('arrow-valuation').textContent).toBe('–')
  })

  it('shows values without arrows in the first year', () => {
    const { container } = render(<RadarChart axes={radarAxesForYear(full as CompanyReport, 2023)} />)
    expect(container.querySelectorAll('[data-testid^="arrow-"]')).toHaveLength(0)
    expect(within(screen.getByTestId('label-stability')).getByText('6')).toBeTruthy()
  })
})

describe('RadarChart with the sparse fixture', () => {
  it('shows a dash, a hollow dot and no arrow for the insufficient_data axis', () => {
    render(<RadarChart axes={radarAxesForYear(sparse as CompanyReport, 2025)} />)
    const label = screen.getByTestId('label-safety')
    expect(within(label).getByText('—')).toBeTruthy()
    expect(screen.getByTestId('vertex-safety').getAttribute('data-hollow')).toBe('true')
    expect(screen.queryByTestId('arrow-safety')).toBeNull()
    expect(screen.getByRole('img').getAttribute('aria-label')).toContain('ביטחון: אין מספיק נתונים')
  })
})

describe('RadarChart with 8 axes', () => {
  it('draws all of them', () => {
    const axes: RadarAxis[] = Array.from({ length: 8 }, (_, i) => ({
      id: `a${i}`,
      label: `ציר ${i}`,
      value: i + 2,
      trend: null,
    }))
    const { container } = render(<RadarChart axes={axes} />)
    expect(container.querySelectorAll('[data-testid^="vertex-"]')).toHaveLength(8)
  })
})

describe('year switcher', () => {
  it('swaps the scores on the client when a year is picked', () => {
    render(<RadarDevPage />)
    const [fullImg] = screen.getAllByRole('img')
    expect(fullImg.getAttribute('aria-label')).toContain('צמיחה 8 מתוך 10')

    const [tab2023] = screen.getAllByRole('tab', { name: '2023' })
    fireEvent.click(tab2023)
    expect(tab2023.getAttribute('aria-selected')).toBe('true')
    expect(screen.getAllByRole('img')[0].getAttribute('aria-label')).toContain('צמיחה 5 מתוך 10')
  })

  it('moves between years with the arrow keys', () => {
    render(<RadarDevPage />)
    const [tab2025] = screen.getAllByRole('tab', { name: '2025' })
    fireEvent.keyDown(tab2025, { key: 'ArrowLeft' })
    expect(screen.getAllByRole('tab', { name: '2024' })[0].getAttribute('aria-selected')).toBe('true')
  })
})
