import { Badge } from '../ui/badge.jsx'

const CHARACTER_LABELS = {
  street_like_mixed: 'Street-Like Mixed',
  high_speed_street: 'High-Speed Street',
  medium_speed_technical: 'Technical',
  high_speed_power: 'Power Circuit',
  slow_technical: 'Slow-Technical',
  high_speed_flowing: 'High-Speed Flowing',
  mixed: 'Mixed',
}

const STYLE_LABELS = {
  late_braker: 'Late-braker',
  v_line: 'V-line',
  u_line: 'U-line',
  balanced: 'Balanced',
}

const ENERGY_LABELS = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  very_high: 'Very High',
}

const DOWNFORCE_LABELS = {
  low: 'Low DF',
  medium_low: 'Med-Low DF',
  medium: 'Medium DF',
  medium_high: 'Med-High DF',
  high: 'High DF',
}

const VERDICT_LABELS = {
  v_line: 'V-line',
  u_line: 'U-line',
  late_braker: 'Late-braker',
  v_line_late_braker: 'V-line / Late-braker',
  u_line_late_braker: 'U-line / Late-braker',
  balanced: 'Balanced',
  v_line_favored: 'V-line favored',
  u_line_favored: 'U-line favored',
  late_braker_favored: 'Late-braker favored',
  v_line_slight_advantage: 'V-line edge',
  u_line_slight_advantage: 'U-line edge',
  late_braker_advantage: 'Late-braker',
}

const SECTOR_COLORS = [
  'hsl(var(--primary))',
  'hsl(var(--time))',
  'hsl(var(--speed))',
]

// ── Map ──────────────────────────────────────────────────────────────────────

const MAP_W = 340
const MAP_H = 210
const PADDING = 20

function validPoints(points) {
  return (points ?? []).filter(
    (p) => typeof p.x === 'number' && typeof p.y === 'number' && typeof p.distance_m === 'number',
  )
}

function getBounds(points) {
  const xs = points.map((p) => p.x)
  const ys = points.map((p) => p.y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const spanX = Math.max(maxX - minX, 1)
  const spanY = Math.max(maxY - minY, 1)
  const scale = Math.min((MAP_W - PADDING * 2) / spanX, (MAP_H - PADDING * 2) / spanY)
  const offsetX = (MAP_W - spanX * scale) / 2
  const offsetY = (MAP_H - spanY * scale) / 2
  return { minX, maxY, scale, offsetX, offsetY }
}

function project(point, bounds) {
  return {
    x: bounds.offsetX + (point.x - bounds.minX) * bounds.scale,
    y: bounds.offsetY + (bounds.maxY - point.y) * bounds.scale,
  }
}

function startFinishMark(points, bounds) {
  if (points.length < 2) return null
  const start = project(points[0], bounds)
  const next = project(points[1], bounds)
  const dx = next.x - start.x
  const dy = next.y - start.y
  const len = Math.hypot(dx, dy) || 1
  const nx = -dy / len
  const ny = dx / len
  const tick = 9
  return {
    x1: start.x - nx * tick, y1: start.y - ny * tick,
    x2: start.x + nx * tick, y2: start.y + ny * tick,
    labelX: Math.min(Math.max(start.x + nx * 16, 14), MAP_W - 14),
    labelY: Math.min(Math.max(start.y + ny * 16, 14), MAP_H - 14),
  }
}

function CircuitMap({ track_map }) {
  if (!track_map) return null
  const { points: rawPoints, total_distance_m } = track_map
  const points = validPoints(rawPoints)
  if (points.length < 3) return null

  const bounds = getBounds(points)
  const sf = startFinishMark(points, bounds)
  const total = total_distance_m || points[points.length - 1].distance_m
  const cuts = [total / 3, (2 * total) / 3]

  const buckets = [
    points.filter((p) => p.distance_m < cuts[0]),
    points.filter((p) => p.distance_m >= cuts[0] && p.distance_m < cuts[1]),
    points.filter((p) => p.distance_m >= cuts[1]),
  ]

  function toPath(pts, bridgePt) {
    const all = bridgePt ? [...pts, bridgePt] : pts
    if (all.length < 2) return null
    return all.map((p, i) => {
      const { x, y } = project(p, bounds)
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
    }).join(' ')
  }

  const paths = [
    toPath(buckets[0], buckets[1]?.[0]),
    toPath(buckets[1], buckets[2]?.[0]),
    toPath(buckets[2]),
  ]

  return (
    <div className="rounded-xl border border-border/60 bg-background/40">
      <div className="flex items-center justify-between px-4 pt-3 pb-1">
        <span className="text-xs font-medium text-muted-foreground">Track map</span>
        <div className="flex items-center gap-4">
          {['S1', 'S2', 'S3'].map((label, i) => (
            <span key={label} className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <span className="inline-block h-2 w-5 rounded-full" style={{ background: SECTOR_COLORS[i] }} />
              {label}
            </span>
          ))}
        </div>
      </div>
      <div className="px-3 pb-3">
        <svg viewBox={`0 0 ${MAP_W} ${MAP_H}`} className="h-48 w-full overflow-visible">
          {paths.map((path, i) => path ? (
            <path key={`o${i}`} d={path} fill="none" stroke="hsl(var(--border))" strokeWidth="12" strokeLinecap="round" strokeLinejoin="round" />
          ) : null)}
          {paths.map((path, i) => path ? (
            <path key={`s${i}`} d={path} fill="none" stroke={SECTOR_COLORS[i]} strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" strokeOpacity="0.88" />
          ) : null)}
          {sf ? (
            <g>
              <line x1={sf.x1} y1={sf.y1} x2={sf.x2} y2={sf.y2} stroke="hsl(var(--foreground))" strokeWidth="2.5" strokeLinecap="round" />
              <line x1={sf.x1} y1={sf.y1} x2={sf.x2} y2={sf.y2} stroke="hsl(var(--card))" strokeWidth="1" strokeLinecap="round" />
              <text x={sf.labelX} y={sf.labelY + 3} textAnchor="middle" fill="hsl(var(--muted-foreground))" fontSize="8" fontFamily="monospace" fontWeight="700">S/F</text>
            </g>
          ) : null}
        </svg>
      </div>
    </div>
  )
}

// ── Sector rows ───────────────────────────────────────────────────────────────

function SectorRow({ index, label, sector }) {
  if (!sector) return null
  const styleLabel = STYLE_LABELS[sector.style_advantage] ?? null
  const energyLabel = ENERGY_LABELS[sector.energy_demand] ?? null

  return (
    <div className="flex items-start gap-3 py-2.5 border-b border-border/40 last:border-b-0">
      <div className="flex items-center gap-1.5 shrink-0 pt-0.5">
        <span
          className="inline-block h-2 w-2 rounded-full shrink-0"
          style={{ background: SECTOR_COLORS[index] }}
        />
        <span className="text-xs font-semibold w-4" style={{ color: SECTOR_COLORS[index] }}>{label}</span>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm leading-5 text-foreground/80">{sector.description}</p>
      </div>
      <div className="flex flex-col items-end gap-1 shrink-0">
        {styleLabel ? <Badge variant="muted" className="text-[10px] px-1.5 py-0">{styleLabel}</Badge> : null}
        {energyLabel ? <span className="text-[10px] text-muted-foreground">ERS: {energyLabel}</span> : null}
      </div>
    </div>
  )
}

// ── Main widget ───────────────────────────────────────────────────────────────

export default function CircuitProfileWidget({ widget }) {
  if (!widget) return null

  const {
    circuit_name,
    character,
    downforce_level,
    sector_1,
    sector_2,
    sector_3,
    energy_profile,
    style_verdict,
    tyre_challenge,
    track_map,
  } = widget

  const characterLabel = CHARACTER_LABELS[character] ?? character ?? '—'
  const downforceLabel = DOWNFORCE_LABELS[downforce_level] ?? null
  const verdictLabel = VERDICT_LABELS[style_verdict?.qualifier] ?? (style_verdict?.qualifier ?? '').replace(/_/g, ' ') || null

  return (
    <div className="rounded-xl border border-border bg-card text-card-foreground shadow-sm">
      {/* Header */}
      <div className="border-b border-border/70 px-5 py-4">
        <div className="text-base font-semibold text-foreground">{circuit_name ?? 'Circuit Profile'}</div>
        <div className="mt-1.5 flex flex-wrap gap-2">
          <Badge variant="default">{characterLabel}</Badge>
          {downforceLabel ? <Badge variant="outline">{downforceLabel}</Badge> : null}
        </div>
      </div>

      <div className="divide-y divide-border/60">

        {/* Track map */}
        {track_map ? (
          <div className="px-5 py-4">
            <CircuitMap track_map={track_map} />
          </div>
        ) : null}

        {/* Track advantage — featured callout */}
        {style_verdict ? (
          <div className="px-5 py-4">
            <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground/70">Track advantage</div>
            <div className="flex items-start gap-3">
              {verdictLabel ? (
                <Badge variant="default" className="mt-0.5 shrink-0 text-[11px]">{verdictLabel}</Badge>
              ) : null}
              <p className="text-sm leading-6 text-foreground/80">{style_verdict.explanation}</p>
            </div>
          </div>
        ) : null}

        {/* Sector breakdown */}
        {(sector_1 || sector_2 || sector_3) ? (
          <div className="px-5 py-3">
            <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground/70">Sectors</div>
            <SectorRow index={0} label="S1" sector={sector_1} />
            <SectorRow index={1} label="S2" sector={sector_2} />
            <SectorRow index={2} label="S3" sector={sector_3} />
          </div>
        ) : null}

        {/* Energy + Tyre — plain language, combined */}
        {(energy_profile?.notes || tyre_challenge) ? (
          <div className="px-5 py-4 space-y-2">
            {energy_profile?.notes ? (
              <div className="flex items-start gap-2">
                <span className="shrink-0 text-xs font-medium text-muted-foreground/70 pt-0.5 w-8">ERS</span>
                <p className="text-sm leading-5 text-muted-foreground">{energy_profile.notes}</p>
              </div>
            ) : null}
            {tyre_challenge ? (
              <div className="flex items-start gap-2">
                <span className="shrink-0 text-xs font-medium text-muted-foreground/70 pt-0.5 w-8">Tyre</span>
                <p className="text-sm leading-5 text-muted-foreground">{tyre_challenge}</p>
              </div>
            ) : null}
          </div>
        ) : null}

      </div>
    </div>
  )
}
