import { Database, Lock, Zap } from 'lucide-react'

import { useMode } from '@/app/mode'
import { cn } from '@/lib/utils'

/** Cached / live switch. Locked to cached, with an explanation, when the server disallows live. */
export function ModeControl() {
  const { mode, setMode, liveAllowed, health, healthError } = useMode()
  const locked = !liveAllowed
  const reason = healthError
    ? 'לא ניתן לבדוק את מצב השרת'
    : health && !health.allow_live
      ? 'השרת מוגדר למצב מטמון בלבד (ALLOW_LIVE=false)'
      : undefined
  return (
    <div className="flex items-center gap-2" data-testid="mode-control" data-mode={mode} data-locked={locked}>
      <div role="radiogroup" aria-label="מצב נתונים" className="bg-muted inline-flex rounded-md p-0.5 text-sm">
        <button
          type="button"
          role="radio"
          aria-checked={mode === 'cached'}
          onClick={() => setMode('cached')}
          className={cn('inline-flex items-center gap-1 rounded px-2.5 py-1', mode === 'cached' && 'bg-background shadow-xs')}
        >
          <Database className="size-3.5" aria-hidden /> מטמון
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={mode === 'live'}
          disabled={locked}
          onClick={() => setMode('live')}
          title={reason}
          className={cn(
            'inline-flex items-center gap-1 rounded px-2.5 py-1 disabled:cursor-not-allowed disabled:opacity-50',
            mode === 'live' && 'bg-background shadow-xs',
          )}
        >
          {locked ? <Lock className="size-3.5" aria-hidden /> : <Zap className="size-3.5" aria-hidden />} חי
        </button>
      </div>
      {locked && reason && <span className="text-muted-foreground hidden text-xs md:inline">{reason}</span>}
    </div>
  )
}
