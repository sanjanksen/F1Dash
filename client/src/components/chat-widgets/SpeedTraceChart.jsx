import { useState } from 'react'

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
  return `${leader} +${Math.abs(value).toFixed(1)} kph`
}

export default function SpeedTraceChart({ points, driverA, driverB, decisiveDistance, decisiveCorner }) {
  const [hoveredDistance, setHoveredDistance] = useState(decisiveDistance ?? null)

  if (!points?.length) return null

  const width = 680
  const height = 190
  const speeds = points.flatMap((point) => [point.speed_a, point.speed_b]).filter((value) => typeof value === 'number')
  const minY = Math.max(0, Math.min(...speeds) - 8)
  const maxY = Math.max(...speeds) + 8
  const maxDistance = Math.max(points[points.length - 1]?.distance_m ?? 1, 1)
  const pathA = linePath(points, width, height, minY, maxY, 'speed_a')
  const pathB = linePath(points, width, height, minY, maxY, 'speed_b')
  const activePoint = nearestPoint(points, hoveredDistance ?? decisiveDistance ?? points[Math.floor(points.length * 0.6)]?.distance_m ?? 0)
  const activeX = ((activePoint?.distance_m ?? 0) / maxDistance) * width
  const decisiveX = decisiveDistance != null ? (decisiveDistance / maxDistance) * width : null

  return (
    <div className="rounded-md border border-border/90 bg-card">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border/90 px-3 py-2.5">
        <div>
          <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
            Speed Trace
          </div>
          <div className="mt-1 text-sm text-muted-foreground">
            Hover the trace to inspect the speed split through the lap.
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-foreground" />
            {driverA}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <svg width="16" height="8" className="shrink-0">
              <line x1="0" y1="4" x2="16" y2="4" stroke="currentColor" strokeWidth="2" strokeDasharray="4 2" className="text-primary/80" />
            </svg>
            {driverB}
          </span>
        </div>
      </div>

      <div className="grid gap-3 px-3 py-3 lg:grid-cols-[minmax(0,1fr)_13rem]">
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
            {[0.2, 0.4, 0.6, 0.8].map((ratio) => (
              <line
                key={ratio}
                x1="0"
                x2={width}
                y1={height * ratio}
                y2={height * ratio}
                className="stroke-border/70"
                strokeWidth="1"
              />
            ))}

            {decisiveX != null ? (
              <>
                <rect x={Math.max(decisiveX - 30, 0)} y="0" width="60" height={height} className="fill-primary/[0.06]" />
                <line x1={decisiveX} x2={decisiveX} y1="0" y2={height} className="stroke-primary/45" strokeDasharray="4 5" strokeWidth="1.25" />
              </>
            ) : null}

            <path d={pathA} fill="none" stroke="currentColor" strokeWidth="2.5" className="text-foreground" />
            <path d={pathB} fill="none" stroke="currentColor" strokeWidth="2.2" className="text-primary/85" strokeDasharray="6 3" />

            {activePoint ? (
              <>
                <line x1={activeX} x2={activeX} y1="0" y2={height} className="stroke-foreground/35" strokeWidth="1" />
                <circle
                  cx={activeX}
                  cy={height - (((activePoint.speed_a ?? minY) - minY) / (maxY - minY)) * height}
                  r="4"
                  className="fill-foreground"
                />
                <circle
                  cx={activeX}
                  cy={height - (((activePoint.speed_b ?? minY) - minY) / (maxY - minY)) * height}
                  r="4"
                  className="fill-primary"
                />
              </>
            ) : null}
          </svg>

          <div className="mt-2 flex items-center justify-between text-[11px] text-muted-foreground">
            <span>0m</span>
            <span>{maxDistance}m</span>
          </div>
        </div>

        <div className="rounded-md border border-border/90 bg-secondary/30 p-3">
          <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
            Cursor Readout
          </div>
          <div className="mt-2 space-y-2 text-sm leading-6 text-foreground">
            <div>
              <div className="text-xs text-muted-foreground">Distance</div>
              <div className="font-medium">{activePoint?.distance_m ?? '—'}m</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Speed split</div>
              <div className="font-medium">{formatDelta(activePoint?.delta_speed, driverA, driverB)}</div>
            </div>
            <div className="grid grid-cols-2 gap-2 pt-1">
              <div>
                <div className="text-xs text-muted-foreground">{driverA}</div>
                <div className="font-medium">{activePoint?.speed_a != null ? `${activePoint.speed_a.toFixed(1)} kph` : '—'}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">{driverB}</div>
                <div className="font-medium">{activePoint?.speed_b != null ? `${activePoint.speed_b.toFixed(1)} kph` : '—'}</div>
              </div>
            </div>
            {decisiveCorner || decisiveDistance != null ? (
              <div className="border-t border-border/80 pt-2">
                <div className="text-xs text-muted-foreground">Decisive zone</div>
                <div className="font-medium">
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
