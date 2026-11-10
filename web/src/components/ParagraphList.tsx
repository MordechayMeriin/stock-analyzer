import { ExternalLink } from 'lucide-react'
import { Fragment } from 'react'

import type { Paragraph } from '@/api/client'
import { pageLabel } from '@/lib/format'
import { cn } from '@/lib/utils'

/** A paragraph's Markdown table text → rows of cells (divider rows dropped). */
function tableRows(text: string): string[][] {
  return text
    .split('\n')
    .filter((line) => line.trim().startsWith('|'))
    .map((line) =>
      line
        .trim()
        .replace(/^\||\|$/g, '')
        .split('|')
        .map((c) => c.trim()),
    )
    .filter((cells) => !cells.every((c) => /^:?-{2,}:?$/.test(c) || c === ''))
}

function TableParagraph({ text }: { text: string }) {
  const rows = tableRows(text)
  if (!rows.length) return <pre className="text-sm whitespace-pre-wrap">{text}</pre>
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <tbody>
          {rows.map((cells, i) => (
            <tr key={i} className="border-b last:border-0">
              {cells.map((c, j) => (
                <td key={j} className="px-2 py-1 align-top">
                  <bdi>{c}</bdi>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function PageMarker({ p }: { p: Paragraph }) {
  return (
    <div className="text-muted-foreground flex items-center gap-2 pt-2 text-xs" data-testid="page-marker" data-page={p.page_index}>
      <span className="bg-border h-px flex-1" />
      {p.citation_url ? (
        <a
          href={p.citation_url}
          target="_blank"
          rel="noreferrer"
          className="hover:text-primary inline-flex items-center gap-1 underline-offset-2 hover:underline"
          data-testid="page-link"
        >
          {pageLabel(p.page_printed, p.page_index)} <ExternalLink className="size-3" aria-hidden />
        </a>
      ) : (
        <span>{pageLabel(p.page_printed, p.page_index)}</span>
      )}
      <span className="bg-border h-px flex-1" />
    </div>
  )
}

/** Paragraphs with a page marker (linked to the PDF page) whenever the page changes. */
export function ParagraphList({ paragraphs, highlight }: { paragraphs: Paragraph[]; highlight?: Set<string> }) {
  return (
    <div className="space-y-3 leading-7" dir="rtl">
      {paragraphs.map((p, i) => (
        <Fragment key={p.pid}>
          {(i === 0 || paragraphs[i - 1].page_index !== p.page_index) && <PageMarker p={p} />}
          <div
            id={p.pid}
            data-pid={p.pid}
            className={cn(highlight?.has(p.pid) && 'bg-amber-50 ring-1 ring-amber-300 dark:bg-amber-950/30', 'rounded px-1')}
          >
            {p.in_table ? (
              <TableParagraph text={p.text} />
            ) : p.heading_level > 0 ? (
              <h3 className={cn('font-semibold', p.heading_level <= 2 ? 'text-lg' : 'text-base')}>{p.text}</h3>
            ) : (
              <p>{p.text}</p>
            )}
          </div>
        </Fragment>
      ))}
    </div>
  )
}
