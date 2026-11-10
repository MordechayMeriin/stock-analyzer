/** The last fiscal year opened for a company, so navigation can link to its report. */
export function rememberedYear(ticker: string | undefined): string | undefined {
  if (!ticker) return undefined
  try {
    return localStorage.getItem(`analyzer.year.${ticker.toUpperCase()}`) ?? undefined
  } catch {
    return undefined
  }
}

export function rememberYear(ticker: string, fy: number | string): void {
  try {
    localStorage.setItem(`analyzer.year.${ticker.toUpperCase()}`, String(fy))
  } catch {
    /* storage unavailable */
  }
}
