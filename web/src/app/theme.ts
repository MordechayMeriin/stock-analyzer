import { useSyncExternalStore } from 'react'

/** 'system' follows the device setting; the other two are the viewer's explicit choice. */
export type ThemeChoice = 'system' | 'light' | 'dark'

const KEY = 'theme'
const media = () => (typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null)
const listeners = new Set<() => void>()

function read(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

/** Puts `.dark` on <html> (the shadcn tokens switch on it) and tells the browser the color scheme. */
export function applyTheme(choice: ThemeChoice = read()): void {
  const dark = choice === 'dark' || (choice === 'system' && !!media()?.matches)
  document.documentElement.classList.toggle('dark', dark)
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
}

export function setTheme(choice: ThemeChoice): void {
  try {
    if (choice === 'system') localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, choice)
  } catch {
    /* private mode: the choice lasts for this page only */
  }
  applyTheme(choice)
  listeners.forEach((l) => l())
}

/** Call once before the first render, so the page never flashes the wrong theme. */
export function initTheme(): void {
  applyTheme()
  media()?.addEventListener('change', () => {
    if (read() === 'system') applyTheme('system')
    listeners.forEach((l) => l())
  })
}

const subscribe = (l: () => void) => {
  listeners.add(l)
  return () => listeners.delete(l)
}

/** The stored choice and whether the page is dark right now. */
export function useTheme(): { choice: ThemeChoice; dark: boolean } {
  const choice = useSyncExternalStore(subscribe, read, () => 'system' as ThemeChoice)
  const dark = useSyncExternalStore(
    subscribe,
    () => document.documentElement.classList.contains('dark'),
    () => false,
  )
  return { choice, dark }
}
