// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import full from '../fixtures/mltm.full.json'
import type { CompanyReport } from '../types'
import { LAST_STEP_MS, RotatingRadar, STEP_MS } from './RotatingRadar'

const report = full as CompanyReport
const label = () => screen.getByRole('img').getAttribute('aria-label') ?? ''
const pressed = (y: number) => screen.getByRole('button', { name: `הצגת ${y}` }).getAttribute('aria-pressed')

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('RotatingRadar', () => {
  it('plays 2023 → 2024 → 2025, then loops back', () => {
    render(<RotatingRadar report={report} />)
    expect(label()).toContain('צמיחה 5 מתוך 10')
    expect(screen.queryByTestId('radar-ghost')).toBeNull()

    act(() => vi.advanceTimersByTime(STEP_MS))
    expect(pressed(2024)).toBe('true')
    expect(label()).toContain('צמיחה 6 מתוך 10')
    expect(screen.getByTestId('radar-ghost')).toBeTruthy() // 2023 outline
    expect(screen.getByTestId('rotation-caption').textContent).toContain('מקווקו: 2023')

    act(() => vi.advanceTimersByTime(STEP_MS))
    expect(label()).toContain('צמיחה 8 מתוך 10')
    act(() => vi.advanceTimersByTime(LAST_STEP_MS))
    expect(pressed(2023)).toBe('true')
  })

  it('stops on pause and on picking a year', () => {
    render(<RotatingRadar report={report} />)
    fireEvent.click(screen.getByRole('button', { name: 'עצירת ההחלפה בין השנים' }))
    act(() => vi.advanceTimersByTime(STEP_MS * 3))
    expect(pressed(2023)).toBe('true')

    fireEvent.click(screen.getByRole('button', { name: 'הפעלת ההחלפה בין השנים' }))
    fireEvent.click(screen.getByRole('button', { name: 'הצגת 2025' }))
    act(() => vi.advanceTimersByTime(STEP_MS * 3))
    expect(pressed(2025)).toBe('true')
    expect(screen.getByRole('button', { name: 'הפעלת ההחלפה בין השנים' })).toBeTruthy()
  })
})
