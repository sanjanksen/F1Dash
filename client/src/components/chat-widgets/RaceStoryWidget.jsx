import { Badge } from '../ui/badge.jsx'
import { Card, CardContent } from '../ui/card.jsx'

function formatRadioTime(dateStr) {
  if (!dateStr) return 'Radio'
  try {
    return new Date(dateStr).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return 'Radio'
  }
}

function formatPitStop(stop) {
  const lap = stop?.pit_window_after_lap
  const compound = stop?.new_compound
  if (lap == null && !compound) return null
  return `Lap ${lap ?? '—'}${compound ? ` → ${compound}` : ''}`
}

function positionStyle(pos) {
  if (!pos) return {}
  if (pos === 1) return { color: 'hsl(var(--podium-gold))', fontWeight: 700 }
  if (pos === 2) return { color: 'hsl(var(--podium-silver))', fontWeight: 700 }
  if (pos === 3) return { color: 'hsl(var(--podium-bronze))', fontWeight: 700 }
  if (pos <= 10) return { color: 'hsl(var(--primary))', fontWeight: 600 }
  return {}
}

function positionBadgeStyle(pos) {
  if (!pos) return {}
  if (pos === 1) return {
    background: 'linear-gradient(135deg, hsl(48 96% 55% / 0.2) 0%, hsl(48 96% 55% / 0.08) 100%)',
    borderColor: 'hsl(48 96% 55% / 0.5)',
    color: 'hsl(var(--podium-gold))',
  }
  if (pos === 2) return {
    background: 'linear-gradient(135deg, hsl(0 0% 75% / 0.15) 0%, hsl(0 0% 75% / 0.05) 100%)',
    borderColor: 'hsl(0 0% 75% / 0.4)',
    color: 'hsl(var(--podium-silver))',
  }
  if (pos === 3) return {
    background: 'linear-gradient(135deg, hsl(28 60% 52% / 0.2) 0%, hsl(28 60% 52% / 0.05) 100%)',
    borderColor: 'hsl(28 60% 52% / 0.45)',
    color: 'hsl(var(--podium-bronze))',
  }
  return {}
}

function compoundColor(compound) {
  const c = (compound || '').toUpperCase()
  if (c === 'SOFT') return 'hsl(0, 75%, 55%)'
  if (c === 'MEDIUM') return 'hsl(48, 96%, 55%)'
  if (c === 'HARD') return 'hsl(0, 0%, 82%)'
  if (c === 'INTER') return 'hsl(140, 60%, 50%)'
  if (c.includes('WET')) return 'hsl(210, 80%, 55%)'
  return 'hsl(var(--muted-foreground))'
}

export default function RaceStoryWidget({ widget }) {
  const finishPos = widget.finish_position
  const badgeStyle = positionBadgeStyle(finishPos)

  return (
    <div className="widget-enter max-w-3xl">
      <Card className="card-accent-primary overflow-hidden">
        <CardContent className="space-y-4 p-4">
          {/* Header */}
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-[9px] font-medium uppercase tracking-[0.22em]" style={{ color: 'hsl(var(--primary) / 0.7)' }}>
                Driver Race Story
              </div>
              <div className="mt-1 flex items-center gap-2 text-base font-semibold tracking-[-0.02em] text-foreground">
                <span>{widget.title}</span>
                {widget.driver_code ? (
                  <Badge variant="muted" className="font-mono-data">{widget.driver_code}</Badge>
                ) : null}
              </div>
              <div className="mt-1 text-sm text-muted-foreground">
                {widget.subtitle}{widget.team ? ` · ${widget.team}` : ''}
              </div>
            </div>
            {finishPos ? (
              <span
                className="inline-flex items-center rounded-md border px-2.5 py-1 text-sm font-bold uppercase tracking-widest"
                style={Object.keys(badgeStyle).length ? badgeStyle : {
                  background: 'hsl(var(--secondary))',
                  borderColor: 'hsl(var(--border))',
                  color: 'hsl(var(--foreground))',
                }}
              >
                P{finishPos}
              </span>
            ) : null}
          </div>

          {/* Stat grid */}
          <div className="grid gap-2.5 sm:grid-cols-4">
            {[
              { label: 'Grid', value: widget.grid_position, prefix: 'P' },
              { label: 'Finish', value: widget.finish_position, prefix: 'P', colored: true },
              { label: 'Points', value: widget.points, prefix: '', colored: false },
              { label: 'Status', value: widget.status, prefix: '', small: true },
            ].map(({ label, value, prefix, colored, small }) => (
              <div key={label} className="rounded-md border border-border/80 bg-secondary/20 px-3 py-2.5">
                <div className="text-[9px] font-medium uppercase tracking-[0.2em] text-muted-foreground/80">{label}</div>
                <div
                  className={`mt-1 font-semibold ${small ? 'text-sm' : 'text-lg'}`}
                  style={colored && value ? positionStyle(value) : {}}
                >
                  {value != null ? `${prefix}${value}` : '—'}
                </div>
              </div>
            ))}
          </div>

          {/* Story line */}
          {widget.story_points?.length ? (
            <div className="rounded-md border border-border/80 bg-secondary/20 px-3 py-3">
              <div className="text-[9px] font-medium uppercase tracking-[0.2em] text-muted-foreground/80">Story Line</div>
              <ul className="mt-2.5 space-y-2 text-sm leading-6 text-foreground">
                {widget.story_points.slice(0, 4).map((point, index) => (
                  <li key={index} className="flex items-start gap-2.5">
                    <span
                      className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full"
                      style={{ background: 'hsl(var(--primary) / 0.7)' }}
                    />
                    <span>{point}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="grid gap-2.5 sm:grid-cols-2">
            {/* Pit stops */}
            <div className="rounded-md border border-border/80 bg-secondary/20 px-3 py-2.5">
              <div className="text-[9px] font-medium uppercase tracking-[0.2em] text-muted-foreground/80">Pit Stops</div>
              {widget.pit_stops?.length ? (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {widget.pit_stops.map((stop, index) => {
                    const label = formatPitStop(stop)
                    if (!label) return null
                    const compound = stop?.new_compound
                    return (
                      <span
                        key={index}
                        className="inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[11px] font-medium"
                        style={{
                          borderColor: 'hsl(var(--border) / 0.9)',
                          color: compound ? compoundColor(compound) : 'hsl(var(--foreground))',
                        }}
                      >
                        {label}
                      </span>
                    )
                  })}
                </div>
              ) : (
                <div className="mt-1 text-sm text-muted-foreground">No stop summary available.</div>
              )}
            </div>

            {/* Race shape */}
            <div className="rounded-md border border-border/80 bg-secondary/20 px-3 py-2.5">
              <div className="text-[9px] font-medium uppercase tracking-[0.2em] text-muted-foreground/80">Race Shape</div>
              <div className="mt-1 space-y-1 text-sm leading-6 text-foreground">
                {widget.interval_summary?.latest_gap_to_leader ? (
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs text-muted-foreground">Gap to leader</span>
                    <span className="font-mono-data font-medium" style={{ color: 'hsl(var(--time))' }}>
                      {widget.interval_summary.latest_gap_to_leader}
                    </span>
                  </div>
                ) : null}
                {widget.interval_summary?.latest_interval ? (
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs text-muted-foreground">Interval</span>
                    <span className="font-mono-data font-medium" style={{ color: 'hsl(var(--time))' }}>
                      {widget.interval_summary.latest_interval}
                    </span>
                  </div>
                ) : null}
                {widget.position_timeline_summary?.earliest_sample_position && widget.position_timeline_summary?.latest_position ? (
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs text-muted-foreground">Position arc</span>
                    <span className="font-mono-data font-medium text-foreground">
                      P{widget.position_timeline_summary.earliest_sample_position} → P{widget.position_timeline_summary.latest_position}
                    </span>
                  </div>
                ) : null}
              </div>
            </div>
          </div>

          {/* Radio highlights */}
          {widget.radio_highlights?.length ? (
            <div className="rounded-md border border-border/80 bg-secondary/20 px-3 py-2.5">
              <div className="text-[9px] font-medium uppercase tracking-[0.2em] text-muted-foreground/80">Radio Highlights</div>
              <ul className="mt-2 space-y-2 text-sm leading-6 text-foreground">
                {widget.radio_highlights.map((message, index) => (
                  <li key={index} className="border-t border-border/60 pt-2 first:border-t-0 first:pt-0">
                    <div className="font-mono-data text-[10px]" style={{ color: 'hsl(var(--time) / 0.8)' }}>
                      {formatRadioTime(message.date)}
                    </div>
                    {message.recording_url ? (
                      <a
                        href={message.recording_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-foreground underline underline-offset-4 hover:text-primary"
                      >
                        Open clip
                      </a>
                    ) : (
                      <span className="text-muted-foreground">Radio clip available</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}
