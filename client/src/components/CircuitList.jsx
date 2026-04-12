import { Badge } from './ui/badge.jsx'
import { Card, CardContent } from './ui/card.jsx'

export default function CircuitList({ circuits }) {
  if (!circuits?.length) return null

  const today = new Date().toISOString().split('T')[0]
  const year = circuits[0]?.date?.slice(0, 4) || new Date().getFullYear()

  return (
    <div>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
            Season calendar
          </div>
          <div className="mt-1 text-lg font-semibold tracking-[-0.03em] text-foreground">
            {year} calendar
          </div>
        </div>
        <Badge variant="muted">{circuits.length} rounds</Badge>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {circuits.map((circuit) => {
          const isPast = circuit.date < today
          return (
            <Card key={circuit.round} className={isPast ? 'opacity-60' : ''}>
              <CardContent className="p-5">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                      Round {String(circuit.round).padStart(2, '0')}
                    </div>
                    <div className="mt-3 text-lg font-semibold tracking-[-0.03em] text-foreground">
                      {circuit.event_name}
                    </div>
                    <div className="mt-1 text-sm text-muted-foreground">{circuit.circuit_name}</div>
                  </div>
                  <Badge variant={isPast ? 'muted' : 'accent'}>{isPast ? 'Completed' : 'Upcoming'}</Badge>
                </div>

                <div className="mt-8 flex items-center justify-between border-t border-border pt-4 text-sm">
                  <span className="text-muted-foreground">{circuit.country}</span>
                  <span className="font-medium text-foreground">
                    {new Date(`${circuit.date}T12:00:00`).toLocaleDateString('en-GB', {
                      day: 'numeric',
                      month: 'short',
                    })}
                  </span>
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
