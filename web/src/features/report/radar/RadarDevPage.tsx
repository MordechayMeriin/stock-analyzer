/** Temporary page (/dev/radar): the radar with both fixtures, for checking it against the design. */
import { useState } from 'react'

import full from '../fixtures/mltm.full.json'
import sparse from '../fixtures/mltm.sparse.json'
import type { CompanyReport } from '../types'
import { defaultYear, radarAxesForYear } from '../view'
import { hasEnoughForRadar } from './geometry'
import { RadarChart } from './RadarChart'
import { YearTabs } from './YearTabs'

const FIXTURES: { name: string; report: CompanyReport }[] = [
  { name: 'mltm.full', report: full as CompanyReport },
  { name: 'mltm.sparse', report: sparse as CompanyReport },
]

function RadarSample({ name, report }: { name: string; report: CompanyReport }) {
  const [year, setYear] = useState(() => defaultYear(report))
  const axes = radarAxesForYear(report, year)
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-[15px] font-semibold">
          {report.company.name_he} <span className="text-sm font-normal text-muted-foreground" dir="ltr">({name})</span>
        </h2>
        <YearTabs years={report.years} value={year} onChange={setYear} />
      </div>
      <RadarChart axes={axes} />
      {!hasEnoughForRadar(axes) && (
        <p className="text-xs text-muted-foreground">
          פחות משלושה צירים עם ערך: במסך החברה יוצג כאן רק הפירוט, בלי רדאר.
        </p>
      )}
    </section>
  )
}

export function RadarDevPage() {
  return (
    <div className="mx-auto max-w-[480px] space-y-9 px-5 py-6">
      <h1 className="text-xl font-bold">רדאר · בדיקה</h1>
      {FIXTURES.map((f) => (
        <RadarSample key={f.name} {...f} />
      ))}
    </div>
  )
}
