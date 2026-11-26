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
        className="size-12 shrink-0 rounded-md object-contain"
      />
    )
  }
  return (
    <div
      data-testid="logo-fallback"
      aria-hidden="true"
      className="flex size-12 shrink-0 items-center justify-center rounded-md bg-black text-xl font-bold text-white"
    >
      {company.name_he.charAt(0)}
    </div>
  )
}

export function CompanyHeader({ report }: { report: CompanyReport }) {
  const { company } = report
  const stale = report.warnings?.some((w) => w.code === 'stale_report')
  return (
    <header className="flex items-start gap-3">
      <Logo company={company} />
      <div className="min-w-0 space-y-1">
        <h1 className="text-xl font-bold">{company.name_he}</h1>
        <p className="text-[13px] text-muted-foreground">
          <span dir="ltr" className="inline-block [unicode-bidi:isolate]">
            {company.ticker}
          </span>{' '}
          · {company.sector.name} · דוח שנתי {report.report.fiscal_year}
        </p>
        {stale && (
          <p className="text-xs text-muted-foreground">
            נכון ל-<span dir="ltr" className="inline-block [unicode-bidi:isolate]">{formatDate(report.report.published_at)}</span>
          </p>
        )}
        {report.summary?.text && <p className="pt-1 text-sm">{report.summary.text}</p>}
      </div>
    </header>
  )
}
