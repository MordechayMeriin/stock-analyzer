import { Link, useParams, useSearchParams } from 'react-router-dom'

import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

import { CompanyHeader } from './components/CompanyHeader'
import { Disclaimer } from './components/Disclaimer'
import { EventsTimeline } from './components/EventsTimeline'
import { KeyMetrics } from './components/KeyMetrics'
import { ScoreList } from './components/ScoreList'
import { hasEnoughForRadar } from './radar/geometry'
import { RadarChart } from './radar/RadarChart'
import { RotatingRadar } from './radar/RotatingRadar'
import { YearTabs, type YearChoice } from './radar/YearTabs'
import { useReport } from './queries'
import { defaultYear, radarAxesForYear, resolveYear } from './view'

// Design A2: 390-wide reference, page padding 28/20/32, 36px between sections; centered up to 480.
const COLUMN = 'mx-auto w-full max-w-[480px] space-y-9 px-5 pt-7 pb-8 text-foreground'

function NewCompanyLink() {
  return (
    <Button asChild variant="ghost" className="-ms-3 min-h-11">
      <Link to="/c">נתח מניה חדשה</Link>
    </Button>
  )
}

function ReportSkeleton() {
  return (
    <div role="status" aria-label="טוען דוח" className={COLUMN}>
      <div className="flex gap-3">
        <Skeleton className="size-12" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-6 w-1/2" />
          <Skeleton className="h-4 w-3/4" />
        </div>
      </div>
      <Skeleton className="aspect-[390/330] w-full" />
      <div className="space-y-2">
        {Array.from({ length: 5 }, (_, i) => (
          <Skeleton key={i} className="h-[54px] w-full" />
        ))}
      </div>
    </div>
  )
}

export function ReportPage() {
  const { ticker = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const query = useReport(ticker)

  if (query.isPending) return <ReportSkeleton />

  if (query.error) {
    const notFound = query.error instanceof ApiError && query.error.status === 404
    return (
      <div className={COLUMN}>
        <div role="alert" className="space-y-3">
          <p className="text-base font-semibold">{notFound ? 'לא מצאנו את הטיקר' : 'משהו השתבש בטעינת הדוח'}</p>
          {!notFound && <p className="text-sm text-muted-foreground">{query.error.message}</p>}
          {!notFound && (
            <Button variant="outline" className="min-h-11" onClick={() => query.refetch()}>
              נסו שוב
            </Button>
          )}
        </div>
        <NewCompanyLink />
      </div>
    )
  }

  const report = query.data
  // ?y=all is the multi-year view: the radar plays through the years; the list below stays on the latest.
  const compare = params.get('y') === 'all' && report.years.length > 1
  const year = compare ? defaultYear(report) : resolveYear(report, params.get('y'))
  const axes = radarAxesForYear(report, year)
  const setYear = (y: YearChoice) => setParams({ y: String(y) }, { replace: true })

  return (
    <div className={COLUMN}>
      <NewCompanyLink />
      <CompanyHeader report={report} />
      <section aria-labelledby="profile-heading">
        <div className="mb-2 flex items-center justify-between gap-3">
          <h2 id="profile-heading" className="text-[15px] font-semibold">
            פרופיל החברה
          </h2>
          <YearTabs
            years={report.years}
            value={compare ? 'all' : year}
            onChange={setYear}
            allLabel={`${report.years.length} שנים`}
          />
        </div>
        {hasEnoughForRadar(axes) && (compare ? <RotatingRadar report={report} /> : <RadarChart axes={axes} />)}
      </section>
      <ScoreList ticker={report.company.ticker} axes={report.profile.axes} year={year} />
      <EventsTimeline events={report.events} years={report.years.length} />
      <KeyMetrics metrics={report.key_metrics} />
      <Disclaimer />
    </div>
  )
}
