import { useState } from 'react'

const COLOR_A = 'hsl(0, 75%, 52%)'
const COLOR_B = 'hsl(186, 100%, 45%)'
const CHART_W = 680
const CHART_H = 180
const DELTA_H = 60

function linePath(points, width, height, minY, maxY, yKey) {
  if (!points.length || maxY <= minY) return ''
  const maxDist = Math.max(points[points.length - 1]?.distance_m ?? 1, 1)
  return points
    .map((p, i) => {
      const x = (p.distance_m / maxDist) * width
      const y = height - (((p[yKey] ?? minY) - minY) / (maxY - minY)) * height
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')
}

function fillPath(points, width, height, minY, maxY, yKey) {
  if (!points.length || maxY <= minY) return ''
  const maxDist = Math.max(points[points.length - 1]?.distance_m ?? 1, 1)
  const coords = points.map((p) => {
    const x = (p.distance_m / maxDist) * width
    const y = height - (((p[yKey] ?? minY) - minY) / (maxY - minY)) * height
    return [x.toFixed(1), y.toFixed(1)]
  })
  const linePart = coords.map(([x, y], i) => `${i === 0 ? 'M' : 'L'} ${x} ${y}`).join(' ')
  const lastX = coords[coords.length - 1][0]
  return `${linePart} L ${lastX} ${height} L 0 ${height} Z`
}

// Delta fill: positive (A faster) fills upward, negative (B faster) fills downward
function deltaFillPath(points, width, height, maxAbs, sign) {
  if (!points.length || maxAbs <= 0) return ''
  const maxDist = Math.max(points[points.length - 1]?.distance_m ?? 1, 1)
  const zeroY = height / 2
  const coords = points.map((p) => {
    const x = (p.distance_m / maxDist) * width
    const delta = p.delta_speed ?? 0
    // For sign=1 (positive/A): clamp to [0, +inf], mirror negative to zero
    // For sign=-1 (negative/B): clamp to [-inf, 0], mirror positive to zero
    const clampedDelta = sign > 0 ? Math.max(delta, 0) : Math.min(delta, 0)
    const y = zeroY - (clampedDelta / maxAbs) * (height / 2)
    return [x.toFixed(1), y.toFixed(1)]
  })
  const linePart = coords.map(([x, y], i) => `${i === 0 ? 'M' : 'L'} ${x} ${y}`).join(' ')
  const lastX = coords[coords.length - 1][0]
  return `${linePart} L ${lastX} ${zeroY} L 0 ${zeroY} Z`
}

function deltaLinePath(points, width, height, maxAbs) {
  if (!points.length || maxAbs <= 0) return ''
  const maxDist = Math.max(points[points.length - 1]?.distance_m ?? 1, 1)
  const zeroY = height / 2
  return points
    .map((p, i) => {
      const x = (p.distance_m / maxDist) * width
      const delta = p.delta_speed ?? 0
      const y = zeroY - (delta / maxAbs) * (height / 2)
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')
}

function nearestPoint(points, cursorDist) {
  if (!points.length) return null
  return points.reduce((best, p) =>
    Math.abs((p.distance_m ?? 0) - cursorDist) < Math.abs((best.distance_m ?? 0) - cursorDist) ? p : best
  )
}

export default function SpeedTraceChart({ points, driverA, driverB, decisiveDistance, decisiveCorner }) {
  const [hoveredDistance, setHoveredDistance] = useState(decisiveDistance ?? null)

  if (!points?.length) return null

  const speeds = points.flatMap((p) => [p.speed_a, p.speed_b]).filter((v) => typeof v === 'number')
  const minY = Math.max(0, Math.min(...speeds) - 8)
  const maxY = Math.max(...speeds) + 8
  const maxDist = Math.max(points[points.length - 1]?.distance_m ?? 1, 1)

  const deltas = points.map((p) => p.delta_speed ?? 0).filter((v) => typeof v === 'number')
  const maxAbsDelta = Math.max(...deltas.map(Math.abs), 1)
  // Round up to a clean number for the y-axis label
  const deltaScale = Math.ceil(maxAbsDelta / 5) * 5

  const pathA = linePath(points, CHART_W, CHART_H, minY, maxY, 'speed_a')
  const pathB = linePath(points, CHART_W, CHART_H, minY, maxY, 'speed_b')
  const fillA = fillPath(points, CHART_W, CHART_H, minY, maxY, 'speed_a')
  const fillB = fillPath(points, CHART_W, CHART_H, minY, maxY, 'speed_b')
  const deltaPos = deltaFillPath(points, CHART_W, DELTA_H, deltaScale, 1)
  const deltaNeg = deltaFillPath(points, CHART_W, DELTA_H, deltaScale, -1)
  const deltaLine = deltaLinePath(points, CHART_W, DELTA_H, deltaScale)

  const activePoint = nearestPoint(
    points,
    hoveredDistance ?? decisiveDistance ?? points[Math.floor(points.length * 0.6)]?.distance_m ?? 0,
  )
  const activeX = ((activePoint?.distance_m ?? 0) / maxDist) * CHART_W
  const decisiveX = decisiveDistance != null ? (decisiveDistance / maxDist) * CHART_W : null

  const delta = activePoint?.delta_speed
  const deltaIsA = typeof delta === 'number' && delta > 0
  const deltaIsB = typeof delta === 'number' && delta < 0
  const deltaColor = deltaIsA ? COLOR_A : deltaIsB ? COLOR_B : 'hsl(var(--muted-foreground))'
  const deltaLabel = typeof delta !== 'number' || delta === 0
    ? 'Level'
    : `${deltaIsA ? driverA : driverB} +${Math.abs(delta).toFixed(1)} kph`

  return (
    <div className="overflow-hidden rounded-md border border-border/80 bg-card">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/80 px-3 py-2.5">
        <div>
          <div className="text-[9px] font-medium uppercase tracking-[0.22em] text-muted-foreground/80">Speed Trace</div>
          <div className="mt-0.5 text-[10px] text-muted-foreground/50">
            Hover to inspect · Delta strip shows where the gap accumulates
          </div>
        </div>
        <div className="flex items-center gap-4 text-[11px]">
          <span className="flex items-center gap-1.5">
            <span className="h-[3px] w-5 rounded-full" style={{ background: COLOR_A }} />
            <span className="font-semibold" style={{ color: COLOR_A }}>{driverA}</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-[3px] w-5 rounded-full" style={{ background: COLOR_B }} />
            <span className="font-semibold" style={{ color: COLOR_B }}>{driverB}</span>
          </span>
        </div>
      </div>

      <div
        className="relative px-3 pt-3"
        onMouseMove={(event) => {
          const bounds = event.currentTarget.getBoundingClientRect()
          const ratio = Math.min(Math.max((event.clientX - bounds.left - 12) / (bounds.width - 24), 0), 1)
          setHoveredDistance(ratio * maxDist)
        }}
        onMouseLeave={() => setHoveredDistance(decisiveDistance ?? null)}
      >
        {/* ── Main speed trace ── */}
        <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`} className="h-44 w-full overflow-visible">
          <defs>
            <linearGradient id="stGradA" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(0,75%,52%)" stopOpacity="0.22" />
              <stop offset="100%" stopColor="hsl(0,75%,52%)" stopOpacity="0" />
            </linearGradient>
            <linearGradient id="stGradB" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(186,100%,45%)" stopOpacity="0.18" />
              <stop offset="100%" stopColor="hsl(186,100%,45%)" stopOpacity="0" />
            </linearGradient>
          </defs>

          {/* Grid */}
          {[0.25, 0.5, 0.75].map((r) => (
            <line key={r} x1="0" x2={CHART_W} y1={CHART_H * r} y2={CHART_H * r}
              stroke="hsl(0,0%,14%)" strokeWidth="1" />
          ))}

          {/* Speed axis labels */}
          {[0.25, 0.5, 0.75].map((r) => {
            const spd = Math.round(minY + (1 - r) * (maxY - minY))
            return (
              <text key={r} x="6" y={CHART_H * r - 4} fill="hsl(0,0%,38%)" fontSize="11" fontFamily="monospace">
                {spd}
              </text>
            )
          })}

          {/* Decisive zone */}
          {decisiveX != null && (
            <>
              <rect x={Math.max(decisiveX - 36, 0)} y="0" width="72" height={CHART_H}
                fill="hsl(0,75%,52%)" fillOpacity="0.05" />
              <line x1={decisiveX} x2={decisiveX} y1="0" y2={CHART_H}
                stroke="hsl(0,75%,52%)" strokeOpacity="0.45" strokeDasharray="4 5" strokeWidth="1.5" />
              {decisiveCorner && (
                <text x={decisiveX + 5} y="14" fill="hsl(0,75%,52%)" fillOpacity="0.7"
                  fontSize="10" fontFamily="monospace">{decisiveCorner}</text>
              )}
            </>
          )}

          {/* Fill areas */}
          <path d={fillB} fill="url(#stGradB)" />
          <path d={fillA} fill="url(#stGradA)" />

          {/* Speed traces */}
          <path d={pathA} fill="none" stroke={COLOR_A} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
          <path d={pathB} fill="none" stroke={COLOR_B} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />

          {/* Cursor */}
          {activePoint && (
            <>
              <line x1={activeX} x2={activeX} y1="0" y2={CHART_H}
                stroke="hsl(0,0%,55%)" strokeOpacity="0.2" strokeWidth="1" />
              <circle cx={activeX}
                cy={CHART_H - (((activePoint.speed_a ?? minY) - minY) / (maxY - minY)) * CHART_H}
                r="4.5" fill={COLOR_A} style={{ filter: 'drop-shadow(0 0 5px hsl(0,75%,52%))' }} />
              <circle cx={activeX}
                cy={CHART_H - (((activePoint.speed_b ?? minY) - minY) / (maxY - minY)) * CHART_H}
                r="4.5" fill={COLOR_B} style={{ filter: 'drop-shadow(0 0 5px hsl(186,100%,45%))' }} />
            </>
          )}
        </svg>

        {/* ── Delta strip ── */}
        <div className="mt-1.5">
          <div className="mb-1 flex items-center gap-2">
            <span className="text-[9px] font-medium uppercase tracking-[0.2em] text-muted-foreground/50">
              Δ Speed (kph)
            </span>
            <span className="rounded px-1.5 py-0.5 text-[10px] font-medium font-mono-data"
              style={{ background: `${deltaColor}18`, color: deltaColor }}>
              {deltaLabel}
            </span>
          </div>
          <svg viewBox={`0 0 ${CHART_W} ${DELTA_H}`} className="w-full overflow-visible"
            style={{ height: `${DELTA_H * 0.6}px` }}>
            <defs>
              <linearGradient id="dGradA" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="hsl(0,75%,52%)" stopOpacity="0.5" />
                <stop offset="100%" stopColor="hsl(0,75%,52%)" stopOpacity="0.08" />
              </linearGradient>
              <linearGradient id="dGradB" x1="0" y1="1" x2="0" y2="0">
                <stop offset="0%" stopColor="hsl(186,100%,45%)" stopOpacity="0.5" />
                <stop offset="100%" stopColor="hsl(186,100%,45%)" stopOpacity="0.08" />
              </linearGradient>
            </defs>

            {/* Zero line */}
            <line x1="0" x2={CHART_W} y1={DELTA_H / 2} y2={DELTA_H / 2}
              stroke="hsl(0,0%,30%)" strokeWidth="1" />

            {/* Y-axis scale labels */}
            <text x="4" y={DELTA_H / 2 - 4} fill="hsl(0,0%,35%)" fontSize="9" fontFamily="monospace">
              +{deltaScale}
            </text>
            <text x="4" y={DELTA_H / 2 + 13} fill="hsl(0,0%,35%)" fontSize="9" fontFamily="monospace">
              -{deltaScale}
            </text>

            {/* Fills */}
            <path d={deltaPos} fill="url(#dGradA)" />
            <path d={deltaNeg} fill="url(#dGradB)" />

            {/* Delta line */}
            <path d={deltaLine} fill="none" stroke="hsl(0,0%,55%)" strokeWidth="1.2"
              strokeLinecap="round" strokeLinejoin="round" strokeOpacity="0.5" />

            {/* Cursor line */}
            {activePoint && (
              <line x1={activeX} x2={activeX} y1="0" y2={DELTA_H}
                stroke="hsl(0,0%,55%)" strokeOpacity="0.2" strokeWidth="1" />
            )}
          </svg>
        </div>

        {/* Distance axis */}
        <div className="mt-1.5 flex items-center justify-between pb-3 text-[10px] font-mono-data text-muted-foreground/50">
          <span>0m</span>
          <span>{maxDist}m</span>
        </div>
      </div>

      {/* Readout footer */}
      <div className="grid grid-cols-3 gap-px border-t border-border/80 bg-border/40">
        {[
          {
            label: 'Distance',
            value: activePoint?.distance_m != null ? `${activePoint.distance_m}m` : '—',
            color: 'hsl(var(--foreground))',
          },
          {
            label: driverA,
            value: activePoint?.speed_a != null ? `${activePoint.speed_a.toFixed(1)} kph` : '—',
            color: COLOR_A,
          },
          {
            label: driverB,
            value: activePoint?.speed_b != null ? `${activePoint.speed_b.toFixed(1)} kph` : '—',
            color: COLOR_B,
          },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-card px-3 py-2">
            <div className="text-[9px] uppercase tracking-[0.2em] text-muted-foreground/60">{label}</div>
            <div className="mt-0.5 font-mono-data text-xs font-medium" style={{ color }}>{value}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
