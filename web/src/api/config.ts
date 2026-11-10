/**
 * API location: runtime `/config.js` (written by the web container from API_BASE_URL),
 * then the build-time VITE_API_BASE_URL, then same origin. No same-origin assumption is
 * required: every request uses this absolute base when set.
 */
export function apiBaseUrl(): string {
  const runtime = typeof window !== 'undefined' ? window.__APP_CONFIG__?.apiBaseUrl : undefined
  const base = runtime || import.meta.env.VITE_API_BASE_URL || ''
  return base.replace(/\/+$/, '')
}
