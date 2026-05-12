const GAUGE_R = 52
const CX = 80
const CY = 72
const STROKE = 10

function arc(cx, cy, r, startDeg, endDeg) {
  const toRad = (d) => (d - 90) * (Math.PI / 180)
  const x1 = cx + r * Math.cos(toRad(startDeg))
  const y1 = cy + r * Math.sin(toRad(startDeg))
  const x2 = cx + r * Math.cos(toRad(endDeg))
  const y2 = cy + r * Math.sin(toRad(endDeg))
  const large = endDeg - startDeg > 180 ? 1 : 0
  return `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2}`
}

function probColor(p) {
  if (p >= 0.65) return 'hsl(var(--destructive))'
  if (p >= 0.50) return 'hsl(35 95% 55%)'
  if (p >= 0.38) return 'hsl(var(--chart-4))'
  return 'hsl(var(--chart-2))'
}

export default function ScProbabilityWidget({ widget }) {
  const {
    circuit_name, race_name,
    sc_probability, sc_probability_pct,
    classification,
    rank_by_sc_probability, circuits_ranked,
    series_average_pct,
    interpretation,
  } = widget

  if (sc_probability === null || sc_probability === undefined) return null

  const fillDeg = sc_probability * 270
  const avgDeg  = (series_average_pct / 100) * 270
  const color   = probColor(sc_probability)

  const START = -135
  const trackEnd = START + 270

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-start gap-6">
        {/* Gauge */}
        <svg width="160" height="110" style={{ flexShrink: 0 }}>
          {/* track */}
          <path
            d={arc(CX, CY, GAUGE_R, START, trackEnd)}
            fill="none"
            stroke="hsl(var(--muted))"
            strokeWidth={STROKE}
            strokeLinecap="round"
          />
          {/* series average tick */}
          <path
            d={arc(CX, CY, GAUGE_R, START + avgDeg - 1, START + avgDeg + 1)}
            fill="none"
            stroke="hsl(var(--muted-foreground))"
            strokeWidth={STROKE + 2}
          />
          {/* fill */}
          <path
            d={arc(CX, CY, GAUGE_R, START, START + fillDeg)}
            fill="none"
            stroke={color}
            strokeWidth={STROKE}
            strokeLinecap="round"
          />
          {/* pct label */}
          <text x={CX} y={CY + 4} textAnchor="middle" fontSize="20" fontWeight="600" fill={color}>
            {sc_probability_pct}%
          </text>
          <text x={CX} y={CY + 18} textAnchor="middle" fontSize="10" fill="hsl(var(--muted-foreground))">
            SC / VSC
          </text>
        </svg>

        {/* Stats */}
        <div className="flex-1 space-y-2 pt-1">
          <div>
            <p className="text-sm font-semibold text-foreground">{circuit_name}</p>
            <p className="text-xs text-muted-foreground">{race_name}</p>
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            <span className="text-muted-foreground">Classification</span>
            <span className="text-foreground capitalize">{classification}</span>
            {rank_by_sc_probability && (
              <>
                <span className="text-muted-foreground">Circuit rank</span>
                <span className="text-foreground">#{rank_by_sc_probability} of {circuits_ranked}</span>
              </>
            )}
            <span className="text-muted-foreground">Series avg</span>
            <span className="text-foreground">{series_average_pct}%</span>
          </div>
        </div>
      </div>

      {interpretation && (
        <p className="text-xs text-muted-foreground leading-5 border-t border-border/60 pt-3">
          {interpretation}
        </p>
      )}
    </div>
  )
}
