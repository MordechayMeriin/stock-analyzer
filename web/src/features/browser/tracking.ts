import type { CompanySearchHit } from '@/api/client'
import { useMode } from '@/app/mode'

/** Adding and removing tracked companies needs live mode (the server refuses it otherwise). */
export function useTrackingGate(): { enabled: boolean; reason: string | undefined } {
  const { mode, liveAllowed } = useMode()
  if (mode === 'live') return { enabled: true, reason: undefined }
  return {
    enabled: false,
    reason: liveAllowed
      ? 'הוספה והסרה של חברות זמינות במצב חי בלבד. עברו למצב חי כדי להשתמש בהן.'
      : 'הוספה והסרה של חברות כבויות: השרת מוגדר למצב מטמון בלבד (ALLOW_LIVE=false).',
  }
}

export interface CompanyDraft {
  ticker: string
  name_he: string
  name_en: string
}

/**
 * The add form's starting values for a provider search hit. The user can edit every field
 * before submitting; ticker and Hebrew name are required.
 */
export function initialDraft(hit: CompanySearchHit): CompanyDraft {
  const name = hit.name.trim()
  const isHebrew = HEBREW_LETTER.test(name)
  return {
    // provider tickers may carry an exchange suffix ("MLTM.TA"); the registry keeps the bare symbol
    ticker: (hit.ticker ?? '').trim().toUpperCase().replace(/\.TA$/, ''),
    // the provider often has only the Latin name: prefill it anyway so the user edits rather than types
    name_he: name,
    name_en: isHebrew ? '' : name,
  }
}

const HEBREW_LETTER = /[א-ת]/
