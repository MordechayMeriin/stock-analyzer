import { ChevronDown, ChevronLeft } from 'lucide-react'
import { useMemo, useState } from 'react'

import type { ReportNode, Structure } from '@/api/client'
import { cn } from '@/lib/utils'

interface Props {
  structure: Structure
  activeId?: string
  onSelect: (node: ReportNode) => void
  /** Show subsections (level ≥ 3) collapsed by default; ancestors of the active node are open. */
  maxOpenLevel?: number
}

function ancestors(byId: Map<string, ReportNode>, id: string | undefined): Set<string> {
  const out = new Set<string>()
  let cur = id ? byId.get(id) : undefined
  while (cur?.parent) {
    out.add(cur.parent)
    cur = byId.get(cur.parent)
  }
  return out
}

/** The report's structure tree; each node shows its number, title and printed page range. */
export function StructureTree({ structure, activeId, onSelect, maxOpenLevel = 1 }: Props) {
  const byId = useMemo(() => new Map(structure.nodes.map((n) => [n.node_id, n])), [structure])
  const [toggled, setToggled] = useState<Record<string, boolean>>({})
  const openPath = useMemo(() => ancestors(byId, activeId), [byId, activeId])

  const isOpen = (n: ReportNode) => toggled[n.node_id] ?? (openPath.has(n.node_id) || n.level <= maxOpenLevel)

  const render = (id: string) => {
    const n = byId.get(id)
    if (!n) return null
    const open = isOpen(n)
    const pages = n.printed_pages[0] !== null ? `עמ' ${n.printed_pages[0]}` : `עמ' ${n.pages[0]} בקובץ`
    return (
      <li key={id}>
        <div className={cn('group flex items-start gap-1 rounded', id === activeId && 'bg-accent')}>
          {n.children.length ? (
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground mt-1 shrink-0"
              aria-label={open ? 'כווץ' : 'הרחב'}
              aria-expanded={open}
              onClick={() => setToggled((t) => ({ ...t, [id]: !open }))}
            >
              {open ? <ChevronDown className="size-4" /> : <ChevronLeft className="size-4" />}
            </button>
          ) : (
            <span className="w-4 shrink-0" />
          )}
          <button
            type="button"
            onClick={() => onSelect(n)}
            className="flex-1 py-0.5 text-start text-sm"
            aria-current={id === activeId ? 'true' : undefined}
            data-node-id={id}
          >
            {n.number && n.kind !== 'chapter' && <><bdi className="text-muted-foreground font-mono text-xs">{n.number}</bdi> </>}
            <span className={n.kind === 'chapter' ? 'font-semibold' : undefined}>{n.title}</span>
            <span className="text-muted-foreground ms-2 text-xs whitespace-nowrap">{pages}</span>
          </button>
        </div>
        {open && n.children.length > 0 && <ul className="ms-4 border-s ps-1">{n.children.map(render)}</ul>}
      </li>
    )
  }

  return (
    <nav aria-label="מבנה הדוח">
      <ul className="space-y-0.5">{structure.roots.map(render)}</ul>
    </nav>
  )
}
