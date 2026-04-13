import { Badge } from '../ui/badge.jsx'
import { Card, CardContent } from '../ui/card.jsx'
import SpeedTraceChart from './SpeedTraceChart.jsx'

function formatGap(value) {
  if (typeof value !== 'number') return null
  return `${Math.abs(value).toFixed(3)}s`
}

export default function QualifyingBattleWidget({ widget }) {
  const points = widget.focus_window_trace?.length ? widget.focus_window_trace : widget.speed_trace
  const decisiveDistance =
    widget.focus_window_trace?.length
      ? widget.focus_window_trace[Math.floor(widget.focus_window_trace.length / 2)]?.distance_m
      : widget.speed_trace?.length
        ? widget.speed_trace[Math.floor(widget.speed_trace.length / 2)]?.distance_m
        : null

  const metricCards = [
    {
      label: 'Overall Gap',
      value: formatGap(widget.overall_gap_s) ?? '—',
      meta: widget.faster_driver ? `${widget.faster_driver} ahead` : null,
    },
    {
      label: 'Decisive Sector',
      value: widget.decisive_sector ?? '—',
      meta: widget.decisive_sector_gap_s != null ? `${formatGap(widget.decisive_sector_gap_s)} of the lap` : null,
    },
    {
      label: 'Key Zone',
      value: widget.decisive_corner ?? 'Lap trace',
      meta: widget.cause_type?.replaceAll('_', ' ') ?? '—',
    },
  ]

  return (
    <div className="max-w-3xl space-y-3">
      <Card>
        <CardContent className="space-y-4 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                Qualifying Battle
              </div>
              <div className="mt-1 text-base font-semibold tracking-[-0.02em] text-foreground">
                {widget.title}
              </div>
              <div className="mt-1 text-sm text-muted-foreground">
                {widget.event} · {widget.session}
              </div>
            </div>
            {widget.faster_driver ? <Badge variant="default">{widget.faster_driver} ahead</Badge> : null}
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            {metricCards.map((card) => (
              <div key={card.label} className="rounded-md border border-border/90 px-3 py-3">
                <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                  {card.label}
                </div>
                <div className="mt-1 text-lg font-semibold text-foreground">{card.value}</div>
                {card.meta ? <div className="mt-1 text-xs text-muted-foreground">{card.meta}</div> : null}
              </div>
            ))}
          </div>

          {widget.zone_summary ? (
            <div className="rounded-md border border-border/90 bg-secondary/35 px-3 py-3 text-sm leading-6 text-foreground">
              {widget.zone_summary}
            </div>
          ) : null}

          {points?.length ? (
            <SpeedTraceChart
              points={points}
              driverA={widget.driver_a || widget.title?.split(' vs ')[0]}
              driverB={widget.driver_b || widget.title?.split(' vs ')[1]}
              decisiveDistance={decisiveDistance}
              decisiveCorner={widget.decisive_corner}
            />
          ) : null}

          <div className={`grid gap-3 ${widget.energy_relevant ? 'sm:grid-cols-2' : ''}`}>
            <div className="rounded-md border border-border/90 px-3 py-3">
              <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">Mechanism</div>
              <div className="mt-1 text-sm leading-6 text-foreground">{widget.cause_explanation}</div>
            </div>
            {widget.energy_relevant ? (
              <div className="rounded-md border border-border/90 px-3 py-3">
                <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">Energy Signal</div>
                <div className="mt-1 text-sm leading-6 text-foreground">{widget.energy_reason}</div>
              </div>
            ) : null}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
