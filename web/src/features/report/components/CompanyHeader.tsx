import { useState } from 'react'

import { formatDate } from '@/lib/format'

import type { Company, CompanyReport } from '../types'

function Logo({ company }: { company: Company }) {
  const [failed, setFailed] = useState(false)
  if (company.logo_url && !failed) {
    return (
      <img
        src={company.logo_url}
        alt=""
        onError={() => setFailed(true)}
        className="size-12 shrink-0 rounded-xl object-contain"
      />
    )
  }
  return (
    <div
      data-testid="logo-fallback"
      aria-hidden="true"
      className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-foreground text-[22px] font-bold text-background"
    >
      {company.name_he.charAt(0)}
    </div>
  )
}

/** Design A2 header: logo, name (20/700), "TICKER · sector · דוח שנתי YYYY", then the summary. */
export function CompanyHeader({ report }: { report: CompanyReport }) {
  const { company } = report
  const stale = report.warnings?.some((w) => w.code === 'stale_report')
  return (
    <header className="flex flex-col gap-4">
      <div className="flex items-center gap-3.5">
        <Logo company={company} />
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="text-xl font-bold">{company.name_he}</h1>
          <p className="text-xs text-muted-foreground">
            <span dir="ltr" className="[unicode-bidi:isolate]">
              {company.ticker}
            </span>{' '}
            · {company.sector.name} · דוח שנתי {report.report.fiscal_year}
          </p>
          {stale && (
            <p className="text-xs text-muted-foreground">
              נכון ל-
              <span dir="ltr" className="[unicode-bidi:isolate]">
                {formatDate(report.report.published_at)}
              </span>
            </p>
          )}
        </div>
      </div>
      {report.summary?.text && <p className="text-[15px] leading-[1.55]">{report.summary.text}</p>}
    </header>
  )
}
