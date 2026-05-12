const METRICS = [
  { key: 'trail_brake_pct',         label: 'Trail braking',       hint: 'High = carries braking into corners' },
  { key: 'throttle_acceptance_pct', label: 'Throttle acceptance', hint: 'High = early power application' },
  { key: 'entry_bravery_pct',       label: 'Entry bravery',       hint: 'High = high entry speed' },
  { key: 'avg_ggv_util_pct',        label: 'GGV utilisation',     hint: 'High = near grip limit throughout' },
]

function MetricBar({ label, value, hint }) {
  if (value === null || value === undefined) return null
  const pct = Math.min(100, Math.max(0, value))
  const color =
    pct >= 65 ? 'hsl(var(--primary))' :
    pct >= 40 ? 'hsl(var(--chart-4))' :
                'hsl(var(--muted-foreground))'

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-foreground">{label}</span>
        <span className="font-mono-data font-medium" style={{ color }}>{pct.toFixed(1)}%</span>
      </div>
      <div className="h-2 rounded-full bg-muted overflow-hidden">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <p className="text-[10px] text-muted-foreground leading-4">{hint}</p>
    </div>
  )
}

export default function StyleFingerprintWidget({ widget }) {
  const {
    driver, round, session,
    corner_count,
    avg_apex_speed_kph,
  } = widget

  if (!driver) return null

  const sessionLabel = session === 'Q' ? 'Qualifying' : session === 'R' ? 'Race' : session

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <span className="text-sm font-semibold text-foreground">{driver}</span>
          <span className="text-xs text-muted-foreground ml-2">Style Fingerprint</span>
        </div>
        <div className="text-right text-xs text-muted-foreground">
          <p>Round {round} · {sessionLabel}</p>
          {corner_count != null && <p>{corner_count} corners</p>}
        </div>
      </div>

      <div className="space-y-4">
        {METRICS.map(({ key, label, hint }) => (
          <MetricBar key={key} label={label} value={widget[key]} hint={hint} />
        ))}
      </div>

      {avg_apex_speed_kph != null && (
        <div className="border-t border-border/60 pt-3 flex justify-between text-xs">
          <span className="text-muted-foreground">Avg apex speed</span>
          <span className="font-mono-data font-medium text-foreground">
            {avg_apex_speed_kph.toFixed(1)} km/h
          </span>
        </div>
      )}
    </div>
  )
}
