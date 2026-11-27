import { ARROWS, describeRadar, radarLayout, toneColor, VIEW_H, VIEW_W, type RadarAxis } from './geometry'

const INK = '#18181b'
const GRID = '#e4e4e7'
const FOREGROUND = '#09090b'
const MUTED = '#71717a'

export interface RadarChartProps {
  /** 3-8 axes, in the order the server sent them. */
  axes: RadarAxis[]
  /** Defaults to a full text description of every axis and score. */
  ariaLabel?: string
}

/**
 * The company-profile radar: a pure view that draws `radarLayout(axes)`. Black polygon on a light
 * grid, a value and a trend arrow at the end of every axis; color only on the arrows. Direction
 * independent: the SVG is LTR inside an RTL page, so its anchors never flip.
 */
export function RadarChart({ axes, ariaLabel }: RadarChartProps) {
  const layout = radarLayout(axes)
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

        {layout.labels.map((l) => {
          return (
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
                      <tspan
                        data-testid={`arrow-${l.id}`}
                        dx={4}
                        fontSize={11}
                        fill={toneColor(l.trend.tone)}
                      >
                        {ARROWS[l.trend.direction]}
                      </tspan>
                    )}
                  </>
                )}
              </text>
            </g>
          )
        })}
      </g>
    </svg>
  )
}
