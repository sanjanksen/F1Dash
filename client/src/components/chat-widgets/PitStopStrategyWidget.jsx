const COMPOUND_COLORS = {
  SOFT: 'hsl(var(--primary))',
  MEDIUM: 'hsl(var(--time))',
  HARD: 'hsl(var(--foreground) / 0.5)',
  INTERMEDIATE: 'hsl(var(--speed))',
  WET: 'hsl(210 80% 55%)',
  UNKNOWN: 'hsl(var(--muted-foreground))',
}
const COMPOUND_SHORT = { SOFT: 'S', MEDIUM: 'M', HARD: 'H', INTERMEDIATE: 'I', WET: 'W', UNKNOWN: '?' }

function StintBar({ stints, pitStops, totalLaps }) {
  if (!totalLaps || !stints?.length) return null
  return (
    <div className="relative h-5 w-full">
      {stints.map((stint, i) => {
        const left = ((stint.start_lap - 1) / totalLaps) * 100
        const width = (stint.laps / totalLaps) * 100
        return (
          <div
            key={i}
            className="absolute top-0 h-full rounded-[2px]"
            style={{
              left: `${left}%`,
              width: `${Math.max(width, 0.5)}%`,
              backgroundColor: COMPOUND_COLORS[stint.compound] ?? COMPOUND_COLORS.UNKNOWN,
              opacity: 0.85,
            }}
            title={`${stint.compound}: laps ${stint.start_lap}–${stint.end_lap}`}
          />
        )
      })}
      {pitStops?.map((pit, i) => (
        <div
          key={i}
          className="absolute top-0 h-full w-px bg-background/90"
          style={{ left: `${((pit.lap - 1) / totalLaps) * 100}%` }}
        />
      ))}
    </div>
  )
}

export default function PitStopStrategyWidget({ widget }) {
  const totalLaps = widget.total_laps
  const drivers = widget.drivers ?? []

  const allDurations = drivers.flatMap((d) => d.pit_stops ?? []).map((p) => p.duration_s).filter(Boolean)
  const fastestPit = allDurations.length ? Math.min(...allDurations) : null

  return (
    <div className="widget-enter max-w-3xl overflow-hidden border-y border-border/80 py-1">
      <div className="flex items-center justify-between py-3">
        <h4 className="text-sm font-medium text-foreground">{widget.event} — strategy</h4>
        <div className="flex gap-3 text-xs text-muted-foreground">
          {['SOFT', 'MEDIUM', 'HARD'].map((c) => (
            <span key={c} className="flex items-center gap-1">
              <span className="inline-block h-2.5 w-2.5 rounded-[2px]" style={{ backgroundColor: COMPOUND_COLORS[c] }} />
              {COMPOUND_SHORT[c]}
            </span>
          ))}
        </div>
      </div>

      <div className="divide-y divide-border/60">
        {drivers.map((d) => (
          <div key={d.driver} className="grid items-center gap-3 py-2 sm:grid-cols-[3.5rem_minmax(0,1fr)_7rem]">
            <div className="text-sm font-medium text-foreground">{d.driver}</div>
            <StintBar stints={d.stints} pitStops={d.pit_stops} totalLaps={totalLaps} />
            <div className="text-right text-xs text-muted-foreground">
              {d.pit_stops?.length
                ? d.pit_stops.map((p, i) => (
                    <span key={i} className="ml-2">
                      {p.duration_s != null ? (
                        <span className={p.duration_s === fastestPit ? 'font-medium text-[hsl(var(--speed))]' : ''}>
                          {p.duration_s.toFixed(2)}s
                        </span>
                      ) : `L${p.lap}`}
                    </span>
                  ))
                : '—'}
            </div>
          </div>
        ))}
      </div>

      <div className="flex gap-1 py-2 text-xs text-muted-foreground">
        <span>Lap 1</span>
        <span className="mx-1 flex-1 self-center border-t border-border/50" />
        <span>{totalLaps ? `Lap ${totalLaps}` : ''}</span>
      </div>
    </div>
  )
}
