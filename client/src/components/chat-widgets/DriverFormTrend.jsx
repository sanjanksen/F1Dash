const W = 560
const H = 130
const PAD = { top: 14, right: 16, bottom: 28, left: 44 }
const INNER_W = W - PAD.left - PAD.right
const INNER_H = H - PAD.top - PAD.bottom

const TREND_COLOR = {
  improving: 'hsl(var(--chart-2))',
  declining: 'hsl(var(--destructive))',
  stable:    'hsl(var(--muted-foreground))',
}

const TREND_LABEL = {
  improving: 'Improving',
  declining: 'Declining',
  stable:    'Stable',
}

export default function DriverFormTrend({ widget }) {
  const { driver, trend, avg_positions_gained, per_race = [], rolling_avg = [] } = widget
  if (!per_race.length) return null

  const gains = per_race.map((r) => r.positions_gained)
  const allVals = [...gains.filter((v) => v !== null), 0]
  const minV = Math.min(...allVals)
  const maxV = Math.max(...allVals)
  const span = Math.max(maxV - minV, 2)
  const pad = span * 0.15

  const toY = (v) => {
    const clamped = Math.max(minV - pad, Math.min(maxV + pad, v ?? 0))
    return PAD.top + INNER_H - ((clamped - (minV - pad)) / (span + 2 * pad)) * INNER_H
  }
  const toX = (i) => PAD.left + (i / Math.max(per_race.length - 1, 1)) * INNER_W

  const zeroY = toY(0)
  const trendColor = TREND_COLOR[trend] || 'hsl(var(--primary))'

  const barWidth = Math.max(4, Math.floor(INNER_W / per_race.length) - 3)

  const rollingPoints = rolling_avg
    .map((v, i) => `${toX(i)},${toY(v)}`)
    .join(' ')

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-foreground tracking-wide">{driver}</span>
          <span className="text-xs text-muted-foreground">Form Trend</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs font-medium" style={{ color: trendColor }}>
            {TREND_LABEL[trend] || trend}
          </span>
          {avg_positions_gained !== null && avg_positions_gained !== undefined && (
            <span className="text-xs text-muted-foreground">
              avg {avg_positions_gained > 0 ? '+' : ''}{avg_positions_gained} pos/race
            </span>
          )}
        </div>
      </div>

      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }}>
        {/* zero line */}
        <line
          x1={PAD.left} y1={zeroY}
          x2={W - PAD.right} y2={zeroY}
          stroke="hsl(var(--border))" strokeWidth="1"
        />

        {/* bars */}
        {per_race.map((race, i) => {
          const v = race.positions_gained
          if (v === null || v === undefined) return null
          const x = toX(i) - barWidth / 2
          const barY = v >= 0 ? toY(v) : zeroY
          const barH = Math.abs(toY(v) - zeroY)
          const color = v > 0
            ? 'hsl(var(--chart-2))'
            : v < 0
            ? 'hsl(var(--destructive))'
            : 'hsl(var(--muted-foreground))'
          return (
            <rect
              key={i}
              x={x} y={barY}
              width={barWidth} height={Math.max(barH, 1)}
              fill={color} opacity="0.7" rx="1"
            />
          )
        })}

        {/* rolling avg line */}
        {rolling_avg.length > 1 && (
          <polyline
            points={rollingPoints}
            fill="none"
            stroke="hsl(var(--foreground))"
            strokeWidth="1.5"
            strokeOpacity="0.6"
            strokeDasharray="4 2"
          />
        )}

        {/* y-axis labels */}
        {[minV, 0, maxV].filter((v, i, arr) => arr.indexOf(v) === i).map((v) => (
          <text
            key={v}
            x={PAD.left - 6} y={toY(v) + 4}
            textAnchor="end"
            fontSize="10"
            fill="hsl(var(--muted-foreground))"
          >
            {v > 0 ? `+${v}` : v}
          </text>
        ))}

        {/* x-axis race labels */}
        {per_race.map((race, i) => (
          <text
            key={i}
            x={toX(i)} y={H - 4}
            textAnchor="middle"
            fontSize="9"
            fill="hsl(var(--muted-foreground))"
          >
            {(race.race_name || '').slice(0, 3).toUpperCase()}
          </text>
        ))}
      </svg>
    </div>
  )
}
