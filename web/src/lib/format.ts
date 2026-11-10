/** Formatting helpers. Decimals arrive as exact strings and are formatted without floats. */

const symbolCache = new Map<string, string>()

export function currencySymbol(currency: string | null | undefined): string {
  if (!currency) return ''
  if (!symbolCache.has(currency)) {
    let symbol = currency
    try {
      const part = new Intl.NumberFormat('he-IL', { style: 'currency', currency })
        .formatToParts(0)
        .find((p) => p.type === 'currency')
      if (part) symbol = part.value
    } catch {
      /* unknown code: show it as is */
    }
    symbolCache.set(currency, symbol)
  }
  return symbolCache.get(currency)!
}

/** "4138004000" → "4,138,004,000"; "-109210000" → "-109,210,000"; "3.38" → "3.38". Exact. */
export function groupDecimal(value: string): string {
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value.trim())
  if (!m) return value
  const [, sign, int, frac] = m
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return `${sign}${grouped}${frac ? `.${frac}` : ''}`
}

/** An exact decimal string in the reporting currency, e.g. "4,138,004,000 ₪". */
export function formatMoney(value: string | null | undefined, currency: string | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const symbol = currencySymbol(currency)
  return symbol ? `${groupDecimal(value)} ${symbol}` : groupDecimal(value)
}

export function formatUsd(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `$${value.toFixed(value > 0 && value < 0.01 ? 4 : 2)}`
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString('he-IL', { year: 'numeric', month: '2-digit', day: '2-digit' })
}

export function formatBytes(n: number | null | undefined): string {
  if (!n) return '—'
  return n > 1_000_000 ? `${(n / 1_000_000).toFixed(1)} MB` : `${Math.round(n / 1000)} KB`
}

export function pageLabel(printed: number | null | undefined, index: number): string {
  return printed !== null && printed !== undefined ? `עמ' ${printed}` : `עמוד ${index} בקובץ`
}
