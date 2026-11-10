import { useQuery } from '@tanstack/react-query'
import { Building2, FileText, MessageSquare, Table2 } from 'lucide-react'
import { NavLink, Outlet, useMatches } from 'react-router-dom'

import { api } from '@/api/client'
import { useMode } from '@/app/mode'
import { ModeControl } from '@/components/ModeControl'
import { cn } from '@/lib/utils'
import { rememberedYear } from '@/lib/years'

function NavItem({ to, icon: Icon, label, disabled }: { to: string; icon: typeof FileText; label: string; disabled?: boolean }) {
  if (disabled) {
    return (
      <span className="text-muted-foreground/50 inline-flex items-center gap-1.5 px-3 py-2 text-sm" aria-disabled>
        <Icon className="size-4" aria-hidden /> {label}
      </span>
    )
  }
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        cn(
          'hover:bg-accent inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-sm',
          isActive && 'bg-accent font-medium',
        )
      }
    >
      <Icon className="size-4" aria-hidden /> {label}
    </NavLink>
  )
}

/** App shell: header with company context, navigation and the mode control. */
export function Layout() {
  // a layout route only sees its own params; the company context comes from the deepest match
  const matches = useMatches()
  const { ticker, fy } = (matches[matches.length - 1]?.params ?? {}) as { ticker?: string; fy?: string }
  const { mode } = useMode()
  const company = useQuery({
    queryKey: ['company', ticker, mode],
    queryFn: ({ signal }) => api.company(ticker!, mode, signal),
    enabled: Boolean(ticker),
  })
  const year = fy ?? rememberedYear(ticker)
  return (
    <div className="min-h-screen">
      <header className="bg-background/95 sticky top-0 z-10 border-b backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <NavLink to="/" className="text-lg font-bold">
            הוועדה
          </NavLink>
          {ticker && (
            <div className="flex items-baseline gap-2" data-testid="company-context">
              <span className="font-medium">{company.data?.name_he ?? ticker}</span>
              <bdi className="text-muted-foreground font-mono text-xs">{ticker.toUpperCase()}</bdi>
              {fy && <bdi className="text-muted-foreground text-xs">FY{fy}</bdi>}
            </div>
          )}
          <nav aria-label="ניווט ראשי" className="flex flex-wrap items-center gap-1">
            <NavItem to={ticker ? `/${ticker}` : '/'} icon={Building2} label="חברה ודוחות" />
            <NavItem to={`/${ticker}/${year}/report`} icon={FileText} label="קריאת דוח" disabled={!ticker || !year} />
            <NavItem to={`/${ticker}/financials`} icon={Table2} label="נתונים כספיים" disabled={!ticker} />
            <NavItem to={`/${ticker}/${year}/playground`} icon={MessageSquare} label="מעבדת LLM" disabled={!ticker || !year} />
          </nav>
          <div className="ms-auto">
            <ModeControl />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
