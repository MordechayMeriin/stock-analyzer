import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { useId, useState, type FormEvent } from 'react'

import { api, type AddCompanyInput, type Company, type CompanySearchHit } from '@/api/client'
import { useMode } from '@/app/mode'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { errorHeadline } from '@/lib/errors'

import { initialDraft, useTrackingGate, type CompanyDraft } from './tracking'

/** After a change to the tracked companies, refresh the list and the search marks. */
function useInvalidateTracking() {
  const qc = useQueryClient()
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ['companies'] }),
      qc.invalidateQueries({ queryKey: ['search'] }),
    ])
}

/** Inline form under an untracked search result: confirm ticker and names, then add. */
export function AddCompanyForm({ hit, onDone }: { hit: CompanySearchHit; onDone: () => void }) {
  const { mode } = useMode()
  const invalidate = useInvalidateTracking()
  const [draft, setDraft] = useState<CompanyDraft>(() => initialDraft(hit))
  const id = useId()
  const add = useMutation({
    mutationFn: (input: AddCompanyInput) => api.addCompany(input, mode),
    onSuccess: async () => {
      await invalidate()
      onDone()
    },
  })
  const ready = draft.ticker.trim() !== '' && draft.name_he.trim() !== ''
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!ready) return
    add.mutate({
      fr_company_id: hit.fr_company_id,
      ticker: draft.ticker.trim(),
      name_he: draft.name_he.trim(),
      name_en: draft.name_en.trim() || null,
      isin: hit.isin ?? null,
    })
  }
  const field = (key: keyof CompanyDraft) => ({
    id: `${id}-${key}`,
    value: draft[key],
    onChange: (e: { target: { value: string } }) => setDraft((d) => ({ ...d, [key]: e.target.value })),
  })

  return (
    <form onSubmit={submit} className="bg-muted/40 space-y-3 px-4 py-3" data-testid={`add-form-${hit.fr_company_id}`}>
      <div className="grid gap-3 sm:grid-cols-[8rem_1fr_1fr]">
        <label className="space-y-1 text-xs" htmlFor={`${id}-ticker`}>
          <span>סימול *</span>
          <Input {...field('ticker')} dir="ltr" className="font-mono uppercase" required maxLength={15} />
        </label>
        <label className="space-y-1 text-xs" htmlFor={`${id}-name_he`}>
          <span>שם בעברית *</span>
          <Input {...field('name_he')} required maxLength={200} />
        </label>
        <label className="space-y-1 text-xs" htmlFor={`${id}-name_en`}>
          <span>שם באנגלית</span>
          <Input {...field('name_en')} dir="ltr" maxLength={200} />
        </label>
      </div>
      {add.error && (
        <p role="alert" className="text-destructive text-sm">
          {errorHeadline(add.error)} <bdi className="text-muted-foreground text-xs">{(add.error as Error).message}</bdi>
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={!ready || add.isPending}>
          <Plus aria-hidden /> {add.isPending ? 'מוסיף…' : 'הוסף למעקב'}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onDone} disabled={add.isPending}>
          ביטול
        </Button>
      </div>
    </form>
  )
}

/** "Stop tracking" for a company added at runtime (YAML companies get no button). */
export function RemoveCompanyButton({ company }: { company: Company }) {
  const { mode } = useMode()
  const gate = useTrackingGate()
  const invalidate = useInvalidateTracking()
  const remove = useMutation({
    mutationFn: () => api.removeCompany(company.ticker, mode),
    onSuccess: invalidate,
  })
  if (company.source !== 'added') return null
  const onClick = () => {
    if (window.confirm(`להפסיק לעקוב אחרי ${company.name_he} (${company.ticker})? הנתונים שכבר נשמרו יישארו.`)) {
      remove.mutate()
    }
  }
  return (
    <div className="flex items-center gap-2 px-1 pt-1">
      {/* the tooltip sits on a wrapper: disabled buttons get no pointer events, so no hover */}
      <span title={gate.reason} className={gate.enabled ? undefined : 'cursor-not-allowed'}>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="text-muted-foreground hover:text-destructive h-7"
          disabled={!gate.enabled || remove.isPending}
          aria-description={gate.reason}
          onClick={onClick}
          data-testid={`remove-${company.ticker}`}
        >
          <Trash2 aria-hidden /> {remove.isPending ? 'מסיר…' : 'הסר ממעקב'}
        </Button>
      </span>
      {remove.error && (
        <span role="alert" className="text-destructive text-xs" title={(remove.error as Error).message}>
          {errorHeadline(remove.error)}
        </span>
      )}
    </div>
  )
}
