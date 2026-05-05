import { Badge } from './ui/badge.jsx'

export default function CircuitList({ circuits }) {
  if (!circuits?.length) return null

  const today = new Date().toISOString().split('T')[0]
  const year = circuits[0]?.date?.slice(0, 4) || new Date().getFullYear()

  return (
    <div>
      <div className="mb-4 flex items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-[-0.03em] text-foreground">{year} calendar</h2>
          <p className="mt-1 text-sm text-muted-foreground">{circuits.length} rounds</p>
        </div>
      </div>

      <div className="overflow-hidden rounded-2xl border border-border/80 bg-card">
        <div className="hidden grid-cols-[5rem_minmax(12rem,1.2fr)_minmax(10rem,1fr)_9rem_8rem] gap-4 border-b border-border/70 px-4 py-2 text-xs font-medium text-muted-foreground md:grid">
          <div>Round</div>
          <div>Grand Prix</div>
          <div>Circuit</div>
          <div>Date</div>
          <div>Status</div>
        </div>

        <div className="divide-y divide-border/70">
          {circuits.map((circuit) => {
            const isPast = circuit.date < today
            const date = new Date(`${circuit.date}T12:00:00`).toLocaleDateString('en-GB', {
              day: 'numeric',
              month: 'short',
            })

            return (
              <div
                key={circuit.round}
                className={isPast ? 'grid gap-2 px-4 py-4 opacity-55 md:grid-cols-[5rem_minmax(12rem,1.2fr)_minmax(10rem,1fr)_9rem_8rem] md:items-center md:gap-4' : 'grid gap-2 px-4 py-4 md:grid-cols-[5rem_minmax(12rem,1.2fr)_minmax(10rem,1fr)_9rem_8rem] md:items-center md:gap-4'}
              >
                <div className="text-sm text-muted-foreground">R{String(circuit.round).padStart(2, '0')}</div>
                <div>
                  <div className="text-sm font-medium text-foreground">{circuit.event_name}</div>
                  <div className="mt-1 text-xs text-muted-foreground md:hidden">{circuit.country}</div>
                </div>
                <div className="text-sm text-muted-foreground">{circuit.circuit_name}</div>
                <div className="text-sm text-foreground">{date}</div>
                <div>
                  <Badge variant={isPast ? 'muted' : 'accent'}>{isPast ? 'Completed' : 'Upcoming'}</Badge>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
