import { useState } from 'react'

const COLOR_A = 'hsl(var(--primary))'
const COLOR_B = 'hsl(var(--speed))'
const DRS_BAND_FILL = 'hsl(120 60% 45% / 0.18)'
const CHART_W = 680
const CHART_H = 180
const DELTA_H = 60

const RANK_COLORS = [
  'hsl(var(--primary))',
  'hsl(var(--time))',
  'hsl(var(--accent))',
]
const RANK_LABELS = ['P', 'S', 'T']
const BAND_HALF_WIDTH = 85

function getDistanceDomain(points, causes = []) {
  const distances = points
    .map((p) => p.distance_m)
    .filter((value) => typeof value === 'number')
  const causeDistances = causes
    .map((cause) => cause.distance_m)
    .filter((value) => typeof value === 'number')
  const allDistances = [...distances, ...causeDistances]
  const min = Math.min(...allDistances)
  const max = Math.max(...allDistances)
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) {
    return { min: 0, max: 1, span: 1 }
  }
  return { min, max, span: max - min }
}

function xForDistance(distance, domain, width) {
  if (typeof distance !== 'number') return 0
  const x = ((distance - domain.min) / domain.span) * width
  return Math.min(Math.max(x, 0), width)
}

function isInDomain(distance, domain) {
  return typeof distance === 'number' && distance >= domain.min && distance <= domain.max
}

function linePath(points, width, height, minY, maxY, yKey, domain) {
  if (!points.length || maxY <= minY) return ''
  return points
    .map((p, i) => {
      const x = xForDistance(p.distance_m, domain, width)
      const y = height - (((p[yKey] ?? minY) - minY) / (maxY - minY)) * height
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')
}

function fillPath(points, width, height, minY, maxY, yKey, domain) {
  if (!points.length || maxY <= minY) return ''
  const coords = points.map((p) => {
    const x = xForDistance(p.distance_m, domain, width)
    const y = height - (((p[yKey] ?? minY) - minY) / (maxY - minY)) * height
    return [x.toFixed(1), y.toFixed(1)]
  })
  const linePart = coords.map(([x, y], i) => `${i === 0 ? 'M' : 'L'} ${x} ${y}`).join(' ')
  const lastX = coords[coords.length - 1][0]
  return `${linePart} L ${lastX} ${height} L 0 ${height} Z`
}

function deltaFillPath(points, width, height, maxAbs, sign, domain) {
  if (!points.length || maxAbs <= 0) return ''
  const zeroY = height / 2
  const coords = points.map((p) => {
    const x = xForDistance(p.distance_m, domain, width)
    const delta = p.delta_speed ?? 0
    const clampedDelta = sign > 0 ? Math.max(delta, 0) : Math.min(delta, 0)
    const y = zeroY - (clampedDelta / maxAbs) * (height / 2)
    return [x.toFixed(1), y.toFixed(1)]
  })
  const linePart = coords.map(([x, y], i) => `${i === 0 ? 'M' : 'L'} ${x} ${y}`).join(' ')
  const lastX = coords[coords.length - 1][0]
  return `${linePart} L ${lastX} ${zeroY} L 0 ${zeroY} Z`
}

function deltaLinePath(points, width, height, maxAbs, domain) {
  if (!points.length || maxAbs <= 0) return ''
  const zeroY = height / 2
  return points
    .map((p, i) => {
      const x = xForDistance(p.distance_m, domain, width)
      const delta = p.delta_speed ?? 0
      const y = zeroY - (delta / maxAbs) * (height / 2)
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')
}

function drsActiveSegments(points) {
  const segments = []
  let start = null
  for (let i = 0; i < points.length; i += 1) {
    const active = !!(points[i]?.drs_a_active || points[i]?.drs_b_active)
    const dist = points[i]?.distance_m
    if (active && start === null) start = dist
    if ((!active || i === points.length - 1) && start !== null) {
      const end = active ? dist : points[i - 1]?.distance_m
      if (typeof start === 'number' && typeof end === 'number' && end > start) {
        segments.push({ start, end })
      }
      start = null
    }
  }
  return segments
}

function nearestPoint(points, cursorDist) {
  if (!points.length) return null
  return points.reduce((best, p) =>
    Math.abs((p.distance_m ?? 0) - cursorDist) < Math.abs((best.distance_m ?? 0) - cursorDist) ? p : best
  )
}

function nearestMechIndex(causes, cursorDist, threshold = 80) {
  if (!causes?.length) return null
  let best = null
  let bestDist = threshold
  causes.forEach((cause, index) => {
    const distance = cause.distance_m
    if (typeof distance !== 'number') return
    const delta = Math.abs(distance - cursorDist)
    if (delta < bestDist) {
      bestDist = delta
      best = index
    }
  })
  return best
}

export default function SpeedTraceChart({
  points,
  driverA,
  driverB,
  decisiveDistance,
  causes = [],
  activeMechIndex,
  onMechHover,
}) {
  const [hoveredDistance, setHoveredDistance] = useState(decisiveDistance ?? null)

  if (!points?.length) return null

  const domain = getDistanceDomain(points, causes)
  const speeds = points.flatMap((p) => [p.speed_a, p.speed_b]).filter((value) => typeof value === 'number')
  const minY = Math.max(0, Math.min(...speeds) - 8)
  const maxY = Math.max(...speeds) + 8

  const deltas = points.map((p) => p.delta_speed ?? 0).filter((value) => typeof value === 'number')
  const maxAbsDelta = Math.max(...deltas.map(Math.abs), 1)
  const deltaScale = Math.ceil(maxAbsDelta / 5) * 5

  const drsSegments = drsActiveSegments(points)
  const hasDrsBand = drsSegments.length > 0
  const pathA = linePath(points, CHART_W, CHART_H, minY, maxY, 'speed_a', domain)
  const pathB = linePath(points, CHART_W, CHART_H, minY, maxY, 'speed_b', domain)
  const fillA = fillPath(points, CHART_W, CHART_H, minY, maxY, 'speed_a', domain)
  const fillB = fillPath(points, CHART_W, CHART_H, minY, maxY, 'speed_b', domain)
  const deltaPos = deltaFillPath(points, CHART_W, DELTA_H, deltaScale, 1, domain)
  const deltaNeg = deltaFillPath(points, CHART_W, DELTA_H, deltaScale, -1, domain)
  const deltaLine = deltaLinePath(points, CHART_W, DELTA_H, deltaScale, domain)

  const activePoint = nearestPoint(
    points,
    hoveredDistance ?? decisiveDistance ?? points[Math.floor(points.length * 0.6)]?.distance_m ?? domain.min,
  )
  const activeX = xForDistance(activePoint?.distance_m, domain, CHART_W)

  const delta = activePoint?.delta_speed
  const deltaIsA = typeof delta === 'number' && delta > 0
  const deltaIsB = typeof delta === 'number' && delta < 0
  const deltaColor = deltaIsA ? COLOR_A : deltaIsB ? COLOR_B : 'hsl(var(--muted-foreground))'
  const deltaLabel = typeof delta !== 'number' || delta === 0
    ? 'Level'
    : `${deltaIsA ? driverA : driverB} +${Math.abs(delta).toFixed(1)} kph`

  function handleMouseMove(event) {
    const bounds = event.currentTarget.getBoundingClientRect()
    const ratio = Math.min(Math.max((event.clientX - bounds.left - 12) / (bounds.width - 24), 0), 1)
    const cursorDist = domain.min + ratio * domain.span
    setHoveredDistance(cursorDist)
    if (onMechHover) onMechHover(nearestMechIndex(causes, cursorDist))
  }

  function handleMouseLeave() {
    setHoveredDistance(decisiveDistance ?? null)
    if (onMechHover) onMechHover(null)
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border/80 bg-card">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/80 px-3 py-2.5">
        <div>
          <div className="text-sm font-medium text-foreground">Speed trace</div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            P/S/T are the same markers explained below.
          </div>
        </div>
        <div className="flex items-center gap-4 text-[11px]">
          {causes.slice(0, 3).map((_, index) => (
            <span key={index} className="flex items-center gap-1 text-xs font-medium" style={{ color: `${RANK_COLORS[index]}cc` }}>
              <span className="inline-flex h-4 w-4 items-center justify-center rounded-sm" style={{ background: `${RANK_COLORS[index]}20` }}>
                {RANK_LABELS[index]}
              </span>
              {index === 0 ? 'Primary' : index === 1 ? 'Secondary' : 'Tertiary'}
            </span>
          ))}
          <span className="ml-1 flex items-center gap-1.5">
            <span className="h-[3px] w-5 rounded-sm" style={{ background: COLOR_A }} />
            <span className="font-semibold" style={{ color: COLOR_A }}>{driverA}</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-[3px] w-5 rounded-sm" style={{ background: COLOR_B }} />
            <span className="font-semibold" style={{ color: COLOR_B }}>{driverB}</span>
          </span>
          {hasDrsBand && (
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-4 rounded-sm" style={{ background: DRS_BAND_FILL }} />
              <span className="text-xs text-muted-foreground">DRS open</span>
            </span>
          )}
        </div>
      </div>

      <div className="relative px-3 pt-3" onMouseMove={handleMouseMove} onMouseLeave={handleMouseLeave}>
        <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`} className="h-44 w-full overflow-visible">
          <defs>
            <linearGradient id="stGradA" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={COLOR_A} stopOpacity="0.16" />
              <stop offset="100%" stopColor={COLOR_A} stopOpacity="0" />
            </linearGradient>
            <linearGradient id="stGradB" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={COLOR_B} stopOpacity="0.12" />
              <stop offset="100%" stopColor={COLOR_B} stopOpacity="0" />
            </linearGradient>
          </defs>

          {[0.25, 0.5, 0.75].map((ratio) => (
            <line key={ratio} x1="0" x2={CHART_W} y1={CHART_H * ratio} y2={CHART_H * ratio}
              stroke="hsl(var(--border))" strokeOpacity="0.65" strokeWidth="1" />
          ))}

          {[0.25, 0.5, 0.75].map((ratio) => {
            const speed = Math.round(minY + (1 - ratio) * (maxY - minY))
            return (
              <text key={ratio} x="6" y={CHART_H * ratio - 4} fill="hsl(var(--muted-foreground))" fontSize="11" fontFamily="monospace">
                {speed}
              </text>
            )
          })}

          {causes.slice(0, 3).map((cause, index) => {
            if (!isInDomain(cause.distance_m, domain)) return null
            const cx = xForDistance(cause.distance_m, domain, CHART_W)
            const bw = (BAND_HALF_WIDTH / domain.span) * CHART_W
            const labelX = Math.min(Math.max(cx, 8), CHART_W - 8)
            const color = RANK_COLORS[index]
            const isActive = activeMechIndex === index

            return (
              <g key={index}>
                <rect
                  x={Math.max(cx - bw, 0)}
                  y={0}
                  width={Math.min(bw * 2, CHART_W - Math.max(cx - bw, 0))}
                  height={CHART_H}
                  fill={color}
                  fillOpacity={isActive ? 0.18 : 0.07}
                />
                <line
                  x1={cx}
                  x2={cx}
                  y1={0}
                  y2={CHART_H}
                  stroke={color}
                  strokeOpacity={isActive ? 0.75 : 0.38}
                  strokeWidth={isActive ? 2 : 1}
                  strokeDasharray="4 4"
                />
                <rect x={labelX - 8} y={2} width={16} height={14} rx={3} fill={color} fillOpacity={isActive ? 0.95 : 0.68} />
                <text x={labelX} y={13} textAnchor="middle" fill="white" fontSize="9" fontFamily="monospace" fontWeight="bold">
                  {RANK_LABELS[index]}
                </text>
              </g>
            )
          })}

          {drsSegments.map((seg, idx) => {
            const xStart = xForDistance(seg.start, domain, CHART_W)
            const xEnd = xForDistance(seg.end, domain, CHART_W)
            const w = Math.max(xEnd - xStart, 1)
            return (
              <rect
                key={`drs-${idx}`}
                x={xStart}
                y={CHART_H - 14}
                width={w}
                height={14}
                fill={DRS_BAND_FILL}
              />
            )
          })}

          <path d={fillB} fill="url(#stGradB)" />
          <path d={fillA} fill="url(#stGradA)" />
          <path d={pathA} fill="none" stroke={COLOR_A} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
          <path d={pathB} fill="none" stroke={COLOR_B} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />

          {activePoint && (
            <>
              <line x1={activeX} x2={activeX} y1="0" y2={CHART_H} stroke="hsl(var(--muted-foreground))" strokeOpacity="0.35" strokeWidth="1" />
              <circle cx={activeX} cy={CHART_H - (((activePoint.speed_a ?? minY) - minY) / (maxY - minY)) * CHART_H} r="4.5" fill={COLOR_A} />
              <circle cx={activeX} cy={CHART_H - (((activePoint.speed_b ?? minY) - minY) / (maxY - minY)) * CHART_H} r="4.5" fill={COLOR_B} />
            </>
          )}
        </svg>

        <div className="mt-1.5">
          <div className="mb-1 flex items-center gap-2">
            <span className="text-xs font-medium text-muted-foreground">Speed delta (kph)</span>
            <span className="rounded px-1.5 py-0.5 font-mono-data text-[10px] font-medium" style={{ background: `${deltaColor}18`, color: deltaColor }}>
              {deltaLabel}
            </span>
          </div>
          <svg viewBox={`0 0 ${CHART_W} ${DELTA_H}`} className="w-full overflow-visible" style={{ height: `${DELTA_H * 0.6}px` }}>
            <defs>
              <linearGradient id="dGradA" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={COLOR_A} stopOpacity="0.35" />
                <stop offset="100%" stopColor={COLOR_A} stopOpacity="0.06" />
              </linearGradient>
              <linearGradient id="dGradB" x1="0" y1="1" x2="0" y2="0">
                <stop offset="0%" stopColor={COLOR_B} stopOpacity="0.35" />
                <stop offset="100%" stopColor={COLOR_B} stopOpacity="0.06" />
              </linearGradient>
            </defs>

            <line x1="0" x2={CHART_W} y1={DELTA_H / 2} y2={DELTA_H / 2} stroke="hsl(var(--border))" strokeWidth="1" />
            <text x="4" y={DELTA_H / 2 - 4} fill="hsl(var(--muted-foreground))" fontSize="9" fontFamily="monospace">+{deltaScale}</text>
            <text x="4" y={DELTA_H / 2 + 13} fill="hsl(var(--muted-foreground))" fontSize="9" fontFamily="monospace">-{deltaScale}</text>

            {causes.slice(0, 3).map((cause, index) => {
              if (!isInDomain(cause.distance_m, domain)) return null
              const cx = xForDistance(cause.distance_m, domain, CHART_W)
              const color = RANK_COLORS[index]
              const isActive = activeMechIndex === index
              return (
                <line key={index} x1={cx} x2={cx} y1={0} y2={DELTA_H}
                  stroke={color} strokeOpacity={isActive ? 0.65 : 0.28}
                  strokeWidth={isActive ? 1.5 : 1} strokeDasharray="3 4" />
              )
            })}

            <path d={deltaPos} fill="url(#dGradA)" />
            <path d={deltaNeg} fill="url(#dGradB)" />
            <path d={deltaLine} fill="none" stroke="hsl(var(--muted-foreground))" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" strokeOpacity="0.5" />
            {activePoint && (
              <line x1={activeX} x2={activeX} y1="0" y2={DELTA_H} stroke="hsl(var(--muted-foreground))" strokeOpacity="0.35" strokeWidth="1" />
            )}
          </svg>
        </div>

        <div className="mt-1.5 flex items-center justify-between pb-3 font-mono-data text-[10px] text-muted-foreground/50">
          <span>{Math.round(domain.min)}m</span>
          <span>{Math.round(domain.max)}m</span>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-px border-t border-border/80 bg-border/40">
        {[
          {
            label: 'Distance',
            value: activePoint?.distance_m != null ? `${activePoint.distance_m}m` : '-',
            color: 'hsl(var(--foreground))',
          },
          {
            label: driverA,
            value: activePoint?.speed_a != null ? `${activePoint.speed_a.toFixed(1)} kph` : '-',
            color: COLOR_A,
          },
          {
            label: driverB,
            value: activePoint?.speed_b != null ? `${activePoint.speed_b.toFixed(1)} kph` : '-',
            color: COLOR_B,
          },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-card px-3 py-2">
            <div className="text-xs text-muted-foreground">{label}</div>
            <div className="mt-0.5 font-mono-data text-xs font-medium" style={{ color }}>{value}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
