import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api, type Health, type Mode } from '@/api/client'

interface ModeState {
  mode: Mode
  setMode: (mode: Mode) => void
  liveAllowed: boolean
  health: Health | undefined
  healthError: Error | null
}

const ModeContext = createContext<ModeState | null>(null)
const STORAGE_KEY = 'analyzer.mode'

function readStoredMode(): Mode {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'live' ? 'live' : 'cached'
  } catch {
    return 'cached'
  }
}

/** Cached/live mode for every request. Live is only possible when /health says the server allows it. */
export function ModeProvider({ children }: { children: ReactNode }) {
  const health = useQuery({ queryKey: ['health'], queryFn: ({ signal }) => api.health(signal), staleTime: 30_000 })
  const liveAllowed = health.data?.allow_live ?? false
  const [requested, setRequested] = useState<Mode>(readStoredMode)
  const mode: Mode = liveAllowed ? requested : 'cached'

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, requested)
    } catch {
      /* storage unavailable */
    }
  }, [requested])

  const setMode = useCallback((m: Mode) => setRequested(m), [])
  const value = useMemo(
    () => ({ mode, setMode, liveAllowed, health: health.data, healthError: health.error as Error | null }),
    [mode, setMode, liveAllowed, health.data, health.error],
  )
  return <ModeContext.Provider value={value}>{children}</ModeContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useMode(): ModeState {
  const ctx = useContext(ModeContext)
  if (!ctx) throw new Error('useMode must be used inside ModeProvider')
  return ctx
}
