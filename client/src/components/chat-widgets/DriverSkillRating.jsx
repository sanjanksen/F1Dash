const W = 480
const H = 60
const PAD = { left: 12, right: 12 }
const IW = W - PAD.left - PAD.right

function CIBar({ mean, hdi5, hdi95, min, max }) {
  const span = max - min || 1
  const toX = (v) => PAD.left + ((v - min) / span) * IW

  const zeroX = toX(0)
  const meanX = toX(mean)
  const lo = toX(hdi5)
  const hi = toX(hdi95)
  const isPositive = mean >= 0

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="block w-full">
      <line x1={zeroX} x2={zeroX} y1={8} y2={H - 16}
        stroke="hsl(var(--muted-foreground))" strokeWidth={1} strokeOpacity={0.4} />
      <text x={zeroX} y={H - 4} textAnchor="middle" fontSize={9}
        fill="hsl(var(--muted-foreground))">0</text>

      <rect x={lo} y={H / 2 - 6} width={hi - lo} height={12}
        fill="hsl(var(--primary))" fillOpacity={0.2} rx={3} />

      <rect x={meanX - 2} y={H / 2 - 10} width={4} height={20}
        fill={isPositive ? 'hsl(var(--primary))' : 'hsl(var(--speed))'}
        rx={2} />

      <text x={lo} y={H - 4} textAnchor="middle" fontSize={8}
        fill="hsl(var(--muted-foreground))">{hdi5 >= 0 ? '+' : ''}{hdi5.toFixed(2)}</text>
      <text x={hi} y={H - 4} textAnchor="middle" fontSize={8}
        fill="hsl(var(--muted-foreground))">{hdi95 >= 0 ? '+' : ''}{hdi95.toFixed(2)}</text>
    </svg>
  )
}

export default function DriverSkillRating({ widget }) {
  if (widget.error) {
    return (
      <div className="widget-enter max-w-md rounded-xl border border-border/80 bg-card px-4 py-3">
        <p className="text-sm text-muted-foreground">{widget.error}</p>
      </div>
    )
  }

  const {
    driver, skill_mean, hdi_5, hdi_95, rank, n_drivers_rated,
    skill_in_seconds, elo_rating, seasons_used, interpretation, built_at_iso,
  } = widget

  const allValues = [hdi_5 ?? -0.5, hdi_95 ?? 0.5, -1, 1]
  const chartMin = Math.min(...allValues) - 0.2
  const chartMax = Math.max(...allValues) + 0.2
  const skillColor = (skill_mean ?? 0) >= 0 ? 'hsl(var(--primary))' : 'hsl(var(--speed))'

  return (
    <div className="widget-enter max-w-lg overflow-hidden rounded-xl border border-border/80 bg-card">
      <div className="border-b border-border/80 px-4 py-3">
        <div className="flex items-center justify-between">
          <div className="text-sm font-medium text-foreground">{driver} — Bayesian skill rating</div>
          <div className="text-xs text-muted-foreground">
            #{rank} of {n_drivers_rated} · {seasons_used?.join('–')}
          </div>
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          Model: Bradley-Terry multilevel · {built_at_iso}
        </div>
      </div>

      <div className="px-4 py-4">
        <div className="mb-4 flex items-baseline gap-3">
          <span className="font-mono-data text-3xl font-bold"
            style={{ color: skillColor }}>
            {(skill_mean ?? 0) >= 0 ? '+' : ''}{skill_mean?.toFixed(2)}
          </span>
          <span className="text-sm text-muted-foreground">SD units</span>
          {skill_in_seconds != null && (
            <span className="ml-1 text-sm" style={{ color: skillColor }}>
              ({skill_in_seconds >= 0 ? '+' : ''}{skill_in_seconds}s/lap vs median)
            </span>
          )}
        </div>

        <div className="mb-1 text-xs text-muted-foreground">
          90% credible interval
        </div>
        <CIBar mean={skill_mean ?? 0} hdi5={hdi_5 ?? -0.5} hdi95={hdi_95 ?? 0.5}
          min={chartMin} max={chartMax} />

        <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {elo_rating != null && (
            <>
              <span>Elo rating</span>
              <span className="font-mono-data text-foreground">{elo_rating.toFixed(0)}</span>
            </>
          )}
          <span>Uncertainty (SD)</span>
          <span className="font-mono-data text-foreground">{widget.skill_std?.toFixed(3)}</span>
        </div>

        {interpretation && (
          <p className="mt-3 text-xs leading-relaxed text-muted-foreground">{interpretation}</p>
        )}
      </div>
    </div>
  )
}
