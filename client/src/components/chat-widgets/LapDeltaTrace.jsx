const W = 600
const H = 140
const PAD = { top: 10, right: 16, bottom: 28, left: 48 }
const IW = W - PAD.left - PAD.right
const IH = H - PAD.top - PAD.bottom

const COLOR_A = 'hsl(var(--primary))'
const COLOR_B = 'hsl(var(--speed))'

function fmtDelta(s) {
  return `${s > 0 ? '+' : ''}${s.toFixed(3)}s`
}

export default function LapDeltaTrace({ widget }) {
  const { driver_a, driver_b, total_delta_s, fastest_driver, lap_time_a_s, lap_time_b_s, delta_trace } = widget
  if (!delta_trace?.length) return null

  const deltas = delta_trace.map((p) => p.delta_s)
  const minD = Math.min(...deltas, 0)
  const maxD = Math.max(...deltas, 0)
  const span = Math.max(Math.abs(minD), Math.abs(maxD), 0.01) * 1.1
  const maxDist = delta_trace[delta_trace.length - 1].distance_m

  const toX = (d) => PAD.left + (d / maxDist) * IW
  const toY = (v) => PAD.top + IH / 2 - (v / span) * (IH / 2)

  const linePts = delta_trace
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${toX(p.distance_m).toFixed(1)} ${toY(p.delta_s).toFixed(1)}`)
    .join(' ')

  const fillAbove = delta_trace
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${toX(p.distance_m).toFixed(1)} ${toY(Math.max(p.delta_s, 0)).toFixed(1)}`)
    .join(' ') + ` L ${toX(maxDist).toFixed(1)} ${toY(0).toFixed(1)} L ${toX(0).toFixed(1)} ${toY(0).toFixed(1)} Z`

  const fillBelow = delta_trace
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${toX(p.distance_m).toFixed(1)} ${toY(Math.min(p.delta_s, 0)).toFixed(1)}`)
    .join(' ') + ` L ${toX(maxDist).toFixed(1)} ${toY(0).toFixed(1)} L ${toX(0).toFixed(1)} ${toY(0).toFixed(1)} Z`

  const zeroY = toY(0)
  const winColor = total_delta_s < 0 ? COLOR_A : COLOR_B

  return (
    <div className="widget-enter max-w-3xl overflow-hidden border-y border-border/80 py-1">
      <div className="flex items-center justify-between py-3">
        <h4 className="text-sm font-medium text-foreground">Lap delta trace</h4>
        <div className="flex items-center gap-4 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="h-[3px] w-4 rounded-sm" style={{ background: COLOR_A }} />
            {driver_a} {lap_time_a_s ? `(${lap_time_a_s.toFixed(3)}s)` : ''}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-[3px] w-4 rounded-sm" style={{ background: COLOR_B }} />
            {driver_b} {lap_time_b_s ? `(${lap_time_b_s.toFixed(3)}s)` : ''}
          </span>
          <span className="font-mono-data font-medium" style={{ color: winColor }}>
            {fastest_driver} {fmtDelta(Math.abs(total_delta_s))}
          </span>
        </div>
      </div>

      <p className="mb-2 text-xs text-muted-foreground">
        Negative (below zero) = {driver_a} ahead at that point. Positive = {driver_b} ahead.
      </p>

      <div className="overflow-x-auto">
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="block">
          <defs>
            <linearGradient id="dtGradA" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={COLOR_B} stopOpacity="0.25" />
              <stop offset="100%" stopColor={COLOR_B} stopOpacity="0.04" />
            </linearGradient>
            <linearGradient id="dtGradB" x1="0" y1="1" x2="0" y2="0">
              <stop offset="0%" stopColor={COLOR_A} stopOpacity="0.25" />
              <stop offset="100%" stopColor={COLOR_A} stopOpacity="0.04" />
            </linearGradient>
          </defs>

          {[-0.5, 0.5].map((frac) => {
            const y = toY(span * frac)
            const label = fmtDelta(span * frac)
            return (
              <g key={frac}>
                <line x1={PAD.left} x2={W - PAD.right} y1={y} y2={y}
                  stroke="hsl(var(--border))" strokeWidth={0.5} />
                <text x={PAD.left - 4} y={y + 4} textAnchor="end" fontSize={9}
                  fill="hsl(var(--muted-foreground))">{label}</text>
              </g>
            )
          })}

          <line x1={PAD.left} x2={W - PAD.right} y1={zeroY} y2={zeroY}
            stroke="hsl(var(--muted-foreground))" strokeWidth={1} strokeOpacity={0.5} />
          <text x={PAD.left - 4} y={zeroY + 4} textAnchor="end" fontSize={9}
            fill="hsl(var(--muted-foreground))">0</text>

          {[0.25, 0.5, 0.75, 1.0].map((frac) => {
            const d = maxDist * frac
            return (
              <text key={frac} x={toX(d)} y={H - 4} textAnchor="middle" fontSize={9}
                fill="hsl(var(--muted-foreground))">{(d / 1000).toFixed(1)}km</text>
            )
          })}

          <path d={fillAbove} fill="url(#dtGradA)" />
          <path d={fillBelow} fill="url(#dtGradB)" />

          <path d={linePts} fill="none" stroke="hsl(var(--muted-foreground))" strokeWidth={2}
            strokeLinecap="round" strokeLinejoin="round" />

          <line x1={PAD.left} x2={PAD.left} y1={PAD.top} y2={H - PAD.bottom}
            stroke="hsl(var(--border))" strokeWidth={1} />
          <line x1={PAD.left} x2={W - PAD.right} y1={H - PAD.bottom} y2={H - PAD.bottom}
            stroke="hsl(var(--border))" strokeWidth={1} />
        </svg>
      </div>
    </div>
  )
}
