const COMPOUND_COLORS = {
  SOFT: 'hsl(var(--primary))',
  MEDIUM: 'hsl(var(--time))',
  HARD: 'hsl(var(--foreground) / 0.55)',
  INTERMEDIATE: 'hsl(var(--speed))',
  WET: 'hsl(210 80% 55%)',
}

const W = 600
const H = 180
const PAD = { top: 12, right: 16, bottom: 36, left: 52 }
const IW = W - PAD.left - PAD.right
const IH = H - PAD.top - PAD.bottom

function fmtTime(s) {
  const m = Math.floor(s / 60)
  const rem = (s % 60).toFixed(3).padStart(6, '0')
  return `${m}:${rem}`
}

export default function DegTrendChart({ widget }) {
  const stints = widget.stints ?? []
  if (!stints.length) return null

  const allPoints = stints.flatMap((s) => s.scatter_data ?? [])
  if (!allPoints.length) return null

  const allAges = allPoints.map((p) => p.tyre_age)
  const allTimes = allPoints.map((p) => p.lap_time_s)
  const minAge = Math.min(...allAges)
  const maxAge = Math.max(...allAges)
  const minTime = Math.min(...allTimes) - 0.3
  const maxTime = Math.max(...allTimes) + 0.3
  const ageSpan = maxAge - minAge || 1
  const timeSpan = maxTime - minTime || 1

  const toX = (age) => PAD.left + ((age - minAge) / ageSpan) * IW
  const toY = (t)   => PAD.top  + ((t - minTime) / timeSpan) * IH

  const tickStep = timeSpan > 4 ? 2 : timeSpan > 1.5 ? 0.5 : 0.2
  const yTicks = []
  let tick = Math.ceil(minTime / tickStep) * tickStep
  while (tick <= maxTime + 0.001) { yTicks.push(tick); tick = Math.round((tick + tickStep) * 1000) / 1000 }

  return (
    <div className="widget-enter max-w-3xl overflow-hidden border-y border-border/80 py-1">
      <div className="flex items-center justify-between py-3">
        <h4 className="text-sm font-medium text-foreground">{widget.title}</h4>
        <div className="flex gap-3">
          {stints.map((s) => (
            <span key={s.compound} className="flex items-center gap-1 text-xs text-muted-foreground">
              <span className="inline-block h-2 w-4 rounded-full"
                style={{ backgroundColor: COMPOUND_COLORS[s.compound] ?? 'hsl(var(--muted-foreground))' }} />
              {s.compound.charAt(0) + s.compound.slice(1).toLowerCase()}
            </span>
          ))}
        </div>
      </div>
      <p className="mb-2 text-xs text-muted-foreground">
        Fuel-corrected lap time vs tyre age — lower = faster. Dots are observed laps; dashed line is regression trend.
      </p>

      <div className="overflow-x-auto">
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="block">
          {yTicks.map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={W - PAD.right} y1={toY(t)} y2={toY(t)}
                stroke="hsl(var(--border))" strokeWidth={0.5} />
              <text x={PAD.left - 4} y={toY(t) + 4} textAnchor="end" fontSize={9}
                fill="hsl(var(--muted-foreground))">{fmtTime(t)}</text>
            </g>
          ))}
          <text x={PAD.left + IW / 2} y={H - 4} textAnchor="middle" fontSize={9}
            fill="hsl(var(--muted-foreground))">Tyre age (laps)</text>

          {stints.map((stint) => {
            const color = COMPOUND_COLORS[stint.compound] ?? 'hsl(var(--muted-foreground))'
            const pts = stint.scatter_data ?? []
            const reg = stint.regression_line ?? []
            const cliffX = stint.cliff_lap_est != null ? toX(stint.cliff_lap_est) : null
            const regPoints = reg.length >= 2
              ? reg.map((pt) => `${toX(pt.tyre_age)},${toY(pt.predicted_s)}`).join(' ')
              : null
            return (
              <g key={stint.compound}>
                {pts.map((pt, i) => (
                  <circle key={i} cx={toX(pt.tyre_age)} cy={toY(pt.lap_time_s)}
                    r={3} fill={color} fillOpacity={0.7} />
                ))}
                {regPoints && (
                  <polyline points={regPoints} fill="none"
                    stroke={color} strokeWidth={1.5} strokeDasharray="4 2" strokeOpacity={0.9} />
                )}
                {cliffX != null && cliffX >= PAD.left && cliffX <= W - PAD.right && (
                  <line x1={cliffX} x2={cliffX} y1={PAD.top} y2={H - PAD.bottom}
                    stroke="hsl(var(--speed))" strokeWidth={1} strokeDasharray="3 3" strokeOpacity={0.6} />
                )}
              </g>
            )
          })}

          <line x1={PAD.left} x2={PAD.left} y1={PAD.top} y2={H - PAD.bottom}
            stroke="hsl(var(--border))" strokeWidth={1} />
          <line x1={PAD.left} x2={W - PAD.right} y1={H - PAD.bottom} y2={H - PAD.bottom}
            stroke="hsl(var(--border))" strokeWidth={1} />
        </svg>
      </div>

      {stints.map((s) => (
        <div key={s.compound} className="border-t border-border/60 py-2 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">
            {s.compound.charAt(0) + s.compound.slice(1).toLowerCase()}
          </span>
          {' '}— {s.lap_count} laps · deg {s.deg_rate_s_per_lap >= 0 ? '+' : ''}{s.deg_rate_s_per_lap?.toFixed(3)}s/lap
          {s.r_squared != null ? ` · R²=${s.r_squared.toFixed(2)}` : ''}
          {s.cliff_lap_est != null && (
            <span style={{ color: 'hsl(var(--speed))' }}>
              {' '}· cliff @age {s.cliff_lap_est}
              {s.laps_past_cliff != null && s.laps_past_cliff > 0
                ? ` (+${s.laps_past_cliff} laps past)`
                : ' (pitted before cliff)'}
            </span>
          )}
        </div>
      ))}
    </div>
  )
}
