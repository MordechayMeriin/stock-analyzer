import { useEffect, useRef, useState } from 'react'

import { ARROWS, describeRadar, radarLayout, toneColor, VIEW_H, VIEW_W, type RadarAxis } from './geometry'

// Theme tokens (index.css), so the chart follows light and dark mode.
const INK = 'var(--foreground)'
const GRID = 'var(--border)'
const FOREGROUND = 'var(--foreground)'
const MUTED = 'var(--muted-foreground)'
/** The previous-year outline: visible over the grid, well under the polygon. */
const GHOST = 'var(--radar-ghost)'
const MORPH_MS = 650

export interface RadarChartProps {
  /** 3-8 axes, in the order the server sent them. */
  axes: RadarAxis[]
  /** A dashed outline behind the polygon (the year the rotation came from), same axis order. */
  ghost?: RadarAxis[]
  /** Defaults to a full text description of every axis and score. */
  ariaLabel?: string
}

const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2)

function prefersReducedMotion(): boolean {
  return typeof window === 'undefined' || !window.matchMedia || window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/**
 * The values the shape is drawn at: when `values` change, glides from where the shape is now to the
 * new values. A missing value jumps; reduced motion jumps everything.
 */
function useMorph(values: (number | null)[]): (number | null)[] {
  const [shown, setShown] = useState(values)
  const current = useRef(values)
  const key = values.join('|')
  useEffect(() => {
    const from = current.current
    const to = values
    if (prefersReducedMotion() || typeof requestAnimationFrame === 'undefined' || from.length !== to.length) {
      current.current = to
      setShown(to)
      return
    }
    let raf = 0
    const start = performance.now()
    const tick = (now: number) => {
      const p = easeInOut(Math.min((now - start) / MORPH_MS, 1))
      const next = to.map((v, i) => {
        const f = from[i]
        return v === null || f === null ? v : f + (v - f) * p
      })
      current.current = next
      setShown(next)
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
    // `key` stands for `values`: a new array with the same numbers must not restart the glide.
  }, [key])
  return shown.length === values.length ? shown : values
}

/**
 * The company-profile radar: black polygon on a light grid, a value and a trend arrow at the end of
 * every axis; color only on the arrows. When the values change (another year) the shape glides to
 * them while the labels switch at once. Direction independent: the SVG is LTR inside an RTL page.
 */
export function RadarChart({ axes, ghost, ariaLabel }: RadarChartProps) {
  const layout = radarLayout(axes)
  const morphed = useMorph(axes.map((a) => a.value))
  const shape = radarLayout(axes.map((a, i) => ({ ...a, value: morphed[i] })))
  const ghostShape = ghost && ghost.length === axes.length ? radarLayout(ghost).polygon : ''
  return (
    <svg
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      role="img"
      aria-label={ariaLabel ?? describeRadar(axes)}
      className="h-auto w-full overflow-visible select-none"
      style={{ direction: 'ltr', fontVariantNumeric: 'tabular-nums' }}
    >
      <g aria-hidden="true">
        {layout.rings.map((ring) => (
          <polygon key={ring.level} points={ring.points} fill="none" stroke={GRID} strokeWidth={1} />
        ))}

        {ghostShape && (
          <polygon
            data-testid="radar-ghost"
            points={ghostShape}
            fill="none"
            stroke={GHOST}
            strokeWidth={1.25}
            strokeDasharray="4 3"
            strokeLinejoin="round"
          />
        )}

        {shape.polygon && (
          <polygon
            data-testid="radar-polygon"
            points={shape.polygon}
            fill={INK}
            fillOpacity={0.12}
            stroke={INK}
            strokeWidth={2}
            strokeLinejoin="round"
          />
        )}

        {shape.vertices.map((v) =>
          v.hollow ? (
            <circle
              key={v.id}
              data-testid={`vertex-${v.id}`}
              data-hollow="true"
              cx={v.point.x}
              cy={v.point.y}
              r={3.5}
              fill="var(--background)"
              stroke={MUTED}
              strokeWidth={1.5}
            />
          ) : (
            <circle key={v.id} data-testid={`vertex-${v.id}`} cx={v.point.x} cy={v.point.y} r={3.5} fill={INK} />
          ),
        )}

        {layout.labels.map((l) => (
          <g key={l.id} data-testid={`label-${l.id}`}>
            <text x={l.x} y={l.nameY} textAnchor="middle" fontSize={12} fontWeight={500} fill={MUTED}>
              {l.label}
            </text>
            <text x={l.x} y={l.valueY} textAnchor="middle" fontSize={16} fontWeight={700} fill={FOREGROUND}>
              {l.value === null ? (
                <tspan fill={MUTED}>—</tspan>
              ) : (
                <>
                  <tspan>{l.value}</tspan>
                  {l.trend && (
                    <tspan data-testid={`arrow-${l.id}`} dx={4} fontSize={11} fill={toneColor(l.trend.tone)}>
                      {ARROWS[l.trend.direction]}
                    </tspan>
                  )}
                </>
              )}
            </text>
          </g>
        ))}
      </g>
    </svg>
  )
}
