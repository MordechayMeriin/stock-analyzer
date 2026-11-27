import {
  ARROWS,
  describeRadar,
  describeRadarHistory,
  historyLayout,
  historyText,
  radarLayout,
  toneColor,
  VIEW_H,
  VIEW_W,
  type RadarAxis,
} from './geometry'

const INK = '#18181b'
const GRID = '#e4e4e7'
const FOREGROUND = '#09090b'
const MUTED = '#71717a'
/** Earlier-year outlines: visible over the #e4e4e7 grid, well under the black front polygon. */
const GHOST = '#a1a1aa'

export interface RadarHistory {
  /** Fiscal years, oldest first. */
  years: number[]
  /** One axes list per year, same axis order as `axes`; the last one is the front year. */
  axes: RadarAxis[][]
}

export interface RadarChartProps {
  /** 3-8 axes, in the order the server sent them: the year drawn in front. */
  axes: RadarAxis[]
  /**
   * When set, the 3-year view: earlier years as outlines behind (previous dashed, older dotted),
   * each axis's year-on-year moves as segments in the server's tone colors, and every value's
   * history under it ("6 · 6 · 7").
   */
  history?: RadarHistory
  /** Defaults to a full text description of every axis and score. */
  ariaLabel?: string
}

/**
 * The company-profile radar: a pure view that draws `radarLayout(axes)`. Black polygon on a light
 * grid, a value and a trend arrow at the end of every axis; color only on the arrows (and, in the
 * 3-year view, on the change segments). Direction independent: the SVG is LTR inside an RTL page.
 */
export function RadarChart({ axes, history, ariaLabel }: RadarChartProps) {
  const layout = radarLayout(axes)
  const past = history ? historyLayout(history.years, history.axes) : null
  const label = ariaLabel ?? (history ? describeRadarHistory(history.years, history.axes) : describeRadar(axes))
  return (
    <svg
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      role="img"
      aria-label={label}
      className="h-auto w-full overflow-visible select-none"
      style={{ direction: 'ltr', fontVariantNumeric: 'tabular-nums' }}
    >
      <g aria-hidden="true">
        {layout.rings.map((ring) => (
          <polygon key={ring.level} points={ring.points} fill="none" stroke={GRID} strokeWidth={1} />
        ))}

        {/* Keyed by the values: a new year (or the 3-year view) remounts this group, replaying the fade. */}
        <g key={`${history ? 'h' : ''}${axes.map((a) => `${a.id}:${a.value}`).join('|')}`} className="radar-fade">
          {past?.ghosts.map((g) => (
            <polygon
              key={g.year}
              data-testid={`ghost-${g.year}`}
              points={g.points}
              fill="none"
              stroke={GHOST}
              strokeWidth={1.25}
              strokeDasharray={g.style === 'dashed' ? '4 3' : '1.5 3'}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ))}

          {layout.polygon && (
            <polygon
              data-testid="radar-polygon"
              points={layout.polygon}
              fill={INK}
              fillOpacity={0.12}
              stroke={INK}
              strokeWidth={2}
              strokeLinejoin="round"
            />
          )}

          {past?.segments.map((s) => (
            <line
              key={`${s.id}-${s.year}`}
              data-testid={`segment-${s.id}-${s.year}`}
              x1={s.from.x}
              y1={s.from.y}
              x2={s.to.x}
              y2={s.to.y}
              stroke={toneColor(s.tone)}
              strokeWidth={3}
              strokeLinecap="round"
            />
          ))}

          {layout.vertices.map((v) =>
            v.hollow ? (
              <circle
                key={v.id}
                data-testid={`vertex-${v.id}`}
                data-hollow="true"
                cx={v.point.x}
                cy={v.point.y}
                r={3.5}
                fill="#ffffff"
                stroke={MUTED}
                strokeWidth={1.5}
              />
            ) : (
              <circle key={v.id} data-testid={`vertex-${v.id}`} cx={v.point.x} cy={v.point.y} r={3.5} fill={INK} />
            ),
          )}

          {layout.labels.map((l, i) => (
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
              {history && (
                <text
                  data-testid={`history-${l.id}`}
                  x={l.x}
                  y={l.valueY + 15}
                  textAnchor="middle"
                  fontSize={11}
                  fill={MUTED}
                >
                  {historyText(history.axes, i)}
                </text>
              )}
            </g>
          ))}
        </g>
      </g>
    </svg>
  )
}
