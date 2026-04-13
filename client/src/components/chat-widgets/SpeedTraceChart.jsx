import { useState } from 'react'

// Colors for driver A (red) and driver B (cyan/speed)
const COLOR_A = 'hsl(0, 75%, 50%)'
const COLOR_B = 'hsl(186, 100%, 45%)'

function linePath(points, width, height, minY, maxY, yKey) {
  if (!points.length || maxY <= minY) return ''
  const maxDistance = Math.max(points[points.length - 1]?.distance_m ?? 1, 1)
  return points
    .map((point, index) => {
      const x = (point.distance_m / maxDistance) * width
      const y = height - (((point[yKey] ?? minY) - minY) / (maxY - minY)) * height
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`
    })
    .join(' ')
}

function fillPath(points, width, height, minY, maxY, yKey) {
  if (!points.length || maxY <= minY) return ''
  const maxDistance = Math.max(points[points.length - 1]?.distance_m ?? 1, 1)
  const coords = points.map((point) => {
    const x = (point.distance_m / maxDistance) * width
    const y = height - (((point[yKey] ?? minY) - minY) / (maxY - minY)) * height
    return [x.toFixed(2), y.toFixed(2)]
  })
  const linePart = coords.map(([x, y], i) => `${i === 0 ? 'M' : 'L'} ${x} ${y}`).join(' ')
  const lastX = coords[coords.length - 1][0]
  return `${linePart} L ${lastX} ${height} L 0 ${height} Z`
}

function nearestPoint(points, cursorDistance) {
  if (!points.length) return null
  return points.reduce((best, point) => {
    if (!best) return point
    return Math.abs((point.distance_m ?? 0) - cursorDistance) < Math.abs((best.distance_m ?? 0) - cursorDistance)
      ? point
      : best
  }, null)
}

function formatDelta(value, driverA, driverB) {
  if (typeof value !== 'number') return '—'
  if (value === 0) return 'Level'
  const leader = value > 0 ? driverA : driverB
  const leaderColor = value > 0 ? COLOR_A : COLOR_B
  return { leader, kph: Math.abs(value).toFixed(1), color: leaderColor }
}

export default function SpeedTraceChart({ points, driverA, driverB, decisiveDistance, decisiveCorner }) {
  const [hoveredDistance, setHoveredDistance] = useState(decisiveDistance ?? null)

  if (!points?.length) return null

  const width = 680
  const height = 190
  const speeds = points.flatMap((p) => [p.speed_a, p.speed_b]).filter((v) => typeof v === 'number')
  const minY = Math.max(0, Math.min(...speeds) - 8)
  const maxY = Math.max(...speeds) + 8
  const maxDistance = Math.max(points[points.length - 1]?.distance_m ?? 1, 1)

  const pathA = linePath(points, width, height, minY, maxY, 'speed_a')
  const pathB = linePath(points, width, height, minY, maxY, 'speed_b')
  const fillA = fillPath(points, width, height, minY, maxY, 'speed_a')
  const fillB = fillPath(points, width, height, minY, maxY, 'speed_b')

  const activePoint = nearestPoint(
    points,
    hoveredDistance ?? decisiveDistance ?? points[Math.floor(points.length * 0.6)]?.distance_m ?? 0,
  )
  const activeX = ((activePoint?.distance_m ?? 0) / maxDistance) * width
  const decisiveX = decisiveDistance != null ? (decisiveDistance / maxDistance) * width : null

  const delta = formatDelta(activePoint?.delta_speed, driverA, driverB)

  return (
    <div className="overflow-hidden rounded-md border border-border/80 bg-card">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/80 px-3 py-2.5">
        <div>
          <div className="text-[9px] font-medium uppercase tracking-[0.22em] text-muted-foreground/80">Speed Trace</div>
          <div className="mt-0.5 text-xs text-muted-foreground/60">Hover to inspect the speed split.</div>
        </div>
        {/* Color-coded driver legend */}
        <div className="flex items-center gap-3 text-[11px]">
          <span className="flex items-center gap-1.5">
            <span className="h-[3px] w-5 rounded-full" style={{ background: COLOR_A }} />
            <span className="font-medium" style={{ color: COLOR_A }}>{driverA}</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-[3px] w-5 rounded-full" style={{ background: COLOR_B }} />
            <span className="font-medium" style={{ color: COLOR_B }}>{driverB}</span>
          </span>
        </div>
      </div>

      <div className="grid gap-3 px-3 py-3 lg:grid-cols-[minmax(0,1fr)_13rem]">
        {/* SVG chart */}
        <div>
          <svg
            viewBox={`0 0 ${width} ${height}`}
            className="h-48 w-full overflow-visible"
            onMouseMove={(event) => {
              const bounds = event.currentTarget.getBoundingClientRect()
              const ratio = Math.min(Math.max((event.clientX - bounds.left) / bounds.width, 0), 1)
              setHoveredDistance(ratio * maxDistance)
            }}
            onMouseLeave={() => setHoveredDistance(decisiveDistance ?? null)}
          >
            <defs>
              {/* Gradient fill under driver A (red) */}
              <linearGradient id="gradA" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="hsl(0, 75%, 50%)" stopOpacity="0.22" />
                <stop offset="100%" stopColor="hsl(0, 75%, 50%)" stopOpacity="0" />
              </linearGradient>
              {/* Gradient fill under driver B (cyan) */}
              <linearGradient id="gradB" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="hsl(186, 100%, 45%)" stopOpacity="0.16" />
                <stop offset="100%" stopColor="hsl(186, 100%, 45%)" stopOpacity="0" />
              </linearGradient>
            </defs>

            {/* Grid lines */}
            {[0.2, 0.4, 0.6, 0.8].map((ratio) => (
              <line
                key={ratio}
                x1="0"
                x2={width}
                y1={height * ratio}
                y2={height * ratio}
                stroke="hsl(0, 0%, 15%)"
                strokeWidth="1"
              />
            ))}

            {/* Decisive zone highlight */}
            {decisiveX != null ? (
              <>
                <rect
                  x={Math.max(decisiveX - 32, 0)}
                  y="0"
                  width="64"
                  height={height}
                  fill="hsl(0, 75%, 50%)"
                  fillOpacity="0.05"
                />
                <line
                  x1={decisiveX}
                  x2={decisiveX}
                  y1="0"
                  y2={height}
                  stroke="hsl(0, 75%, 50%)"
                  strokeOpacity="0.5"
                  strokeDasharray="4 5"
                  strokeWidth="1.25"
                />
              </>
            ) : null}

            {/* Fill areas (rendered behind lines) */}
            <path d={fillB} fill="url(#gradB)" />
            <path d={fillA} fill="url(#gradA)" />

            {/* Speed traces */}
            <path d={pathA} fill="none" stroke={COLOR_A} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
            <path d={pathB} fill="none" stroke={COLOR_B} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />

            {/* Cursor crosshair + dots */}
            {activePoint ? (
              <>
                <line
                  x1={activeX}
                  x2={activeX}
                  y1="0"
                  y2={height}
                  stroke="hsl(0, 0%, 60%)"
                  strokeOpacity="0.25"
                  strokeWidth="1"
                />
                <circle
                  cx={activeX}
                  cy={height - (((activePoint.speed_a ?? minY) - minY) / (maxY - minY)) * height}
                  r="4.5"
                  fill={COLOR_A}
                  style={{ filter: 'drop-shadow(0 0 4px hsl(0, 75%, 50%))' }}
                />
                <circle
                  cx={activeX}
                  cy={height - (((activePoint.speed_b ?? minY) - minY) / (maxY - minY)) * height}
                  r="4.5"
                  fill={COLOR_B}
                  style={{ filter: 'drop-shadow(0 0 4px hsl(186, 100%, 45%))' }}
                />
              </>
            ) : null}
          </svg>

          {/* Distance axis */}
          <div className="mt-1 flex items-center justify-between text-[10px] font-mono-data text-muted-foreground/60">
            <span>0m</span>
            <span>{maxDistance}m</span>
          </div>
        </div>

        {/* Cursor readout */}
        <div className="rounded-md border border-border/80 bg-secondary/25 p-3">
          <div className="text-[9px] font-medium uppercase tracking-[0.22em] text-muted-foreground/70">
            Cursor Readout
          </div>
          <div className="mt-2.5 space-y-2.5 text-sm">
            <div>
              <div className="text-[10px] text-muted-foreground/60">Distance</div>
              <div className="font-mono-data font-medium text-foreground">
                {activePoint?.distance_m ?? '—'}m
              </div>
            </div>

            <div>
              <div className="text-[10px] text-muted-foreground/60">Speed split</div>
              {typeof delta === 'object' ? (
                <div className="font-medium" style={{ color: delta.color }}>
                  {delta.leader} +{delta.kph} kph
                </div>
              ) : (
                <div className="font-medium text-muted-foreground">Level</div>
              )}
            </div>

            <div className="grid grid-cols-2 gap-2 border-t border-border/60 pt-2">
              <div>
                <div className="text-[10px]" style={{ color: `${COLOR_A}99` }}>{driverA}</div>
                <div className="font-mono-data font-medium" style={{ color: COLOR_A }}>
                  {activePoint?.speed_a != null ? `${activePoint.speed_a.toFixed(1)}` : '—'}
                  <span className="text-[10px] font-normal text-muted-foreground/60"> kph</span>
                </div>
              </div>
              <div>
                <div className="text-[10px]" style={{ color: `${COLOR_B}99` }}>{driverB}</div>
                <div className="font-mono-data font-medium" style={{ color: COLOR_B }}>
                  {activePoint?.speed_b != null ? `${activePoint.speed_b.toFixed(1)}` : '—'}
                  <span className="text-[10px] font-normal text-muted-foreground/60"> kph</span>
                </div>
              </div>
            </div>

            {decisiveCorner || decisiveDistance != null ? (
              <div className="border-t border-border/60 pt-2">
                <div className="text-[10px] text-muted-foreground/60">Decisive zone</div>
                <div className="font-medium" style={{ color: 'hsl(var(--time))' }}>
                  {decisiveCorner ?? `${decisiveDistance}m`}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  )
}
