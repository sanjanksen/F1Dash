function WinBar({ rateA, rateB, driverA, driverB }) {
  const pctA = Math.round((rateA ?? 0) * 100)
  const pctB = Math.round((rateB ?? 0) * 100)
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-muted-foreground mb-1">
        <span>{driverA}</span>
        <span>{driverB}</span>
      </div>
      <div className="flex h-4 rounded-full overflow-hidden bg-muted">
        <div
          className="flex items-center justify-center text-[10px] font-semibold text-white"
          style={{ width: `${pctA}%`, background: 'hsl(var(--primary))' }}
        >
          {pctA > 8 ? `${pctA}%` : ''}
        </div>
        <div
          className="flex items-center justify-center text-[10px] font-semibold text-white ml-auto"
          style={{ width: `${pctB}%`, background: 'hsl(var(--chart-4))' }}
        >
          {pctB > 8 ? `${pctB}%` : ''}
        </div>
      </div>
    </div>
  )
}

function RaceRow({ race, driverA, driverB }) {
  const aWon = race.winner === driverA
  const bWon = race.winner === driverB
  return (
    <div className="grid grid-cols-[3rem_1fr_2rem_2rem_2rem_2rem_3rem] gap-1 items-center text-xs py-1 border-b border-border/40 last:border-0">
      <span className="text-muted-foreground tabular-nums">{race.season}</span>
      <span className="text-foreground truncate">{race.race_name}</span>
      <span className={`tabular-nums text-right font-medium ${aWon ? 'text-foreground' : 'text-muted-foreground'}`}>
        {race.a_position ?? '–'}
      </span>
      <span className="text-muted-foreground text-center text-[10px]">vs</span>
      <span className={`tabular-nums text-left font-medium ${bWon ? 'text-foreground' : 'text-muted-foreground'}`}>
        {race.b_position ?? '–'}
      </span>
      <span className="text-[10px] text-muted-foreground text-right">
        {race.winner ? (aWon ? '◀' : '▶') : '='}
      </span>
      <span className="text-[10px] text-muted-foreground text-right">{race.circuit?.slice(0, 8)}</span>
    </div>
  )
}

export default function HeadToHeadHistory({ widget }) {
  const {
    driver_a, driver_b,
    seasons_analysed = [],
    races_together,
    driver_a_wins, driver_b_wins, ties,
    driver_a_win_rate, driver_b_win_rate,
    avg_position_delta,
    dominant_driver,
    per_race = [],
  } = widget

  if (!driver_a || !driver_b) return null

  const seasonsStr = seasons_analysed.length ? seasons_analysed.join(', ') : ''
  const recent = per_race.slice(-20)

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-foreground">{driver_a}</span>
          <span className="text-xs text-muted-foreground">vs</span>
          <span className="text-sm font-semibold text-foreground">{driver_b}</span>
        </div>
        {seasonsStr && (
          <span className="text-xs text-muted-foreground">{seasonsStr}</span>
        )}
      </div>

      <WinBar rateA={driver_a_win_rate} rateB={driver_b_win_rate} driverA={driver_a} driverB={driver_b} />

      <div className="grid grid-cols-4 gap-3 text-center">
        {[
          { label: `${driver_a} wins`, value: driver_a_wins },
          { label: `${driver_b} wins`, value: driver_b_wins },
          { label: 'Ties', value: ties },
          { label: 'Races', value: races_together },
        ].map(({ label, value }) => (
          <div key={label} className="space-y-0.5">
            <p className="text-base font-semibold text-foreground tabular-nums">{value ?? '–'}</p>
            <p className="text-[10px] text-muted-foreground">{label}</p>
          </div>
        ))}
      </div>

      {avg_position_delta !== null && avg_position_delta !== undefined && (
        <p className="text-xs text-muted-foreground">
          Avg position delta: <span className="text-foreground font-medium">
            {avg_position_delta > 0 ? `${driver_a} +${avg_position_delta.toFixed(1)}` : `${driver_b} +${Math.abs(avg_position_delta).toFixed(1)}`}
          </span> places ahead
          {dominant_driver && dominant_driver !== 'evenly matched' && (
            <> — <span className="text-foreground font-medium">{dominant_driver}</span> dominant</>
          )}
        </p>
      )}

      {recent.length > 0 && (
        <div className="space-y-0">
          <div className="grid grid-cols-[3rem_1fr_2rem_2rem_2rem_2rem_3rem] gap-1 text-[10px] text-muted-foreground pb-1 border-b border-border">
            <span>Season</span>
            <span>Race</span>
            <span className="text-right">{driver_a}</span>
            <span />
            <span>{driver_b}</span>
            <span />
            <span className="text-right">Circuit</span>
          </div>
          {recent.map((race, i) => (
            <RaceRow key={i} race={race} driverA={driver_a} driverB={driver_b} />
          ))}
        </div>
      )}
    </div>
  )
}
