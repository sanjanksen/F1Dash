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

  const driverA = widget.driver_a || widget.title?.split(' vs ')[0]
  const driverB = widget.driver_b || widget.title?.split(' vs ')[1]
  const fasterIsA = widget.faster_driver === driverA

  const metricCards = [
    {
      label: 'Overall Gap',
      value: formatGap(widget.overall_gap_s) ?? '—',
      meta: widget.faster_driver ? `${widget.faster_driver} faster` : null,
      accentColor: 'hsl(var(--time))',
      topBorder: 'card-accent-time',
    },
    {
      label: 'Decisive Sector',
      value: widget.decisive_sector ?? '—',
      meta: widget.decisive_sector_gap_s != null ? `${formatGap(widget.decisive_sector_gap_s)} delta` : null,
      accentColor: 'hsl(var(--primary))',
      topBorder: 'card-accent-primary',
    },
    {
      label: 'Key Zone',
      value: widget.decisive_corner ?? 'Lap trace',
      meta: widget.cause_type?.replaceAll('_', ' ') ?? '—',
      accentColor: 'hsl(var(--speed))',
      topBorder: 'card-accent-speed',
    },
  ]

  return (
    <div className="widget-enter max-w-3xl space-y-3">
      <Card className="card-accent-primary overflow-hidden">
        <CardContent className="space-y-4 p-4">
          {/* Header: driver vs driver */}
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-[9px] font-medium uppercase tracking-[0.22em]" style={{ color: 'hsl(var(--primary) / 0.7)' }}>
                Qualifying Battle
              </div>
              <div className="mt-1.5 flex items-center gap-2.5">
                <span
                  className="rounded px-2 py-0.5 text-sm font-bold uppercase tracking-wide"
                  style={{
                    background: 'hsl(var(--primary) / 0.12)',
                    border: '1px solid hsl(var(--primary) / 0.3)',
                    color: 'hsl(var(--primary))',
                    fontFamily: 'var(--font-display)',
                    fontSize: '0.95rem',
                    letterSpacing: '0.04em',
                  }}
                >
                  {driverA}
                </span>
                <span className="text-xs text-muted-foreground">vs</span>
                <span
                  className="rounded px-2 py-0.5 text-sm font-bold uppercase tracking-wide"
                  style={{
                    background: 'hsl(var(--speed) / 0.10)',
                    border: '1px solid hsl(var(--speed) / 0.3)',
                    color: 'hsl(var(--speed))',
                    fontFamily: 'var(--font-display)',
                    fontSize: '0.95rem',
                    letterSpacing: '0.04em',
                  }}
                >
                  {driverB}
                </span>
              </div>
              <div className="mt-1 text-sm text-muted-foreground">
                {widget.event} · {widget.session}
              </div>
            </div>
            {widget.faster_driver ? (
              <span
                className="inline-flex items-center rounded-md border px-2.5 py-1 text-xs font-semibold uppercase tracking-wider"
                style={{
                  background: 'linear-gradient(135deg, hsl(48 96% 55% / 0.15) 0%, hsl(48 96% 55% / 0.05) 100%)',
                  borderColor: 'hsl(48 96% 55% / 0.4)',
                  color: 'hsl(var(--podium-gold))',
                }}
              >
                {widget.faster_driver} faster
              </span>
            ) : null}
          </div>

          {/* Metric cards */}
          <div className="grid gap-2.5 sm:grid-cols-3">
            {metricCards.map((card) => (
              <div
                key={card.label}
                className={`${card.topBorder} rounded-md border border-border/80 bg-secondary/20 px-3 py-2.5`}
              >
                <div className="text-[9px] font-medium uppercase tracking-[0.2em] text-muted-foreground/80">
                  {card.label}
                </div>
                <div
                  className="mt-1 text-lg font-semibold font-mono-data"
                  style={{ color: card.accentColor }}
                >
                  {card.value}
                </div>
                {card.meta ? (
                  <div className="mt-0.5 text-xs text-muted-foreground">{card.meta}</div>
                ) : null}
              </div>
            ))}
          </div>

          {/* Zone summary */}
          {widget.zone_summary ? (
            <div
              className="rounded-md border px-3 py-3 text-sm leading-6 text-foreground"
              style={{
                background: 'linear-gradient(135deg, hsl(var(--primary) / 0.05) 0%, hsl(var(--secondary)) 100%)',
                borderColor: 'hsl(var(--primary) / 0.2)',
              }}
            >
              {widget.zone_summary}
            </div>
          ) : null}

          {/* Speed trace */}
          {points?.length ? (
            <SpeedTraceChart
              points={points}
              driverA={driverA}
              driverB={driverB}
              decisiveDistance={decisiveDistance}
              decisiveCorner={widget.decisive_corner}
            />
          ) : null}

          {/* Mechanism / energy */}
          <div className={`grid gap-2.5 ${widget.energy_relevant ? 'sm:grid-cols-2' : ''}`}>
            <div className="rounded-md border border-border/80 bg-secondary/20 px-3 py-2.5">
              <div className="text-[9px] font-medium uppercase tracking-[0.2em] text-muted-foreground/80">Mechanism</div>
              <div className="mt-1 text-sm leading-6 text-foreground">{widget.cause_explanation}</div>
            </div>
            {widget.energy_relevant ? (
              <div className="card-accent-speed rounded-md border border-border/80 bg-secondary/20 px-3 py-2.5">
                <div className="text-[9px] font-medium uppercase tracking-[0.2em]" style={{ color: 'hsl(var(--speed) / 0.75)' }}>
                  Energy Signal
                </div>
                <div className="mt-1 text-sm leading-6 text-foreground">{widget.energy_reason}</div>
              </div>
            ) : null}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
