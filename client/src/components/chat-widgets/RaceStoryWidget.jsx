import { Badge } from '../ui/badge.jsx'

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
  return `Lap ${lap ?? '-'}${compound ? `, ${compound}` : ''}`
}

function positionTone(pos) {
  if (pos === 1) return 'text-[hsl(var(--podium-gold))]'
  if (pos === 2) return 'text-[hsl(var(--podium-silver))]'
  if (pos === 3) return 'text-[hsl(var(--podium-bronze))]'
  if (pos <= 10) return 'text-primary'
  return 'text-foreground'
}

export default function RaceStoryWidget({ widget }) {
  const finishPos = widget.finish_position

  return (
    <div className="widget-enter max-w-3xl overflow-hidden border-y border-border/80 py-1">
      <div className="grid gap-px bg-border/70 md:grid-cols-[minmax(0,1fr)_12rem]">
        <div className="bg-background py-4 pr-4">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold text-foreground">{widget.title}</h3>
            {widget.driver_code ? <Badge variant="muted">{widget.driver_code}</Badge> : null}
          </div>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            {widget.subtitle}{widget.team ? `, ${widget.team}` : ''}
          </p>
        </div>
        <div className="bg-background py-4 md:text-right">
          <div className="text-xs text-muted-foreground">Finish</div>
          <div className={`mt-1 text-3xl font-semibold tracking-[-0.05em] ${positionTone(finishPos)}`}>
            {finishPos ? `P${finishPos}` : '-'}
          </div>
        </div>
      </div>

      <div className="grid gap-px bg-border/70 sm:grid-cols-4">
        {[
          ['Grid', widget.grid_position != null ? `P${widget.grid_position}` : '-'],
          ['Points', widget.points ?? '-'],
          ['Status', widget.status ?? '-'],
          ['Team', widget.team ?? '-'],
        ].map(([label, value]) => (
          <div key={label} className="bg-background px-0 py-3 sm:px-4">
            <div className="text-xs text-muted-foreground">{label}</div>
            <div className="mt-1 truncate text-sm font-medium text-foreground">{value}</div>
          </div>
        ))}
      </div>

      <div className="divide-y divide-border">
        {widget.story_points?.length ? (
          <section className="py-4">
            <h4 className="text-sm font-medium text-foreground">Race story</h4>
            <ol className="mt-3 space-y-2 text-sm leading-6 text-foreground">
              {widget.story_points.slice(0, 4).map((point, index) => (
                <li key={index} className="grid grid-cols-[1.5rem_minmax(0,1fr)] gap-2">
                  <span className="font-mono-data text-xs text-muted-foreground">{index + 1}</span>
                  <span>{point}</span>
                </li>
              ))}
            </ol>
          </section>
        ) : null}

        <section className="grid gap-px bg-border/70 sm:grid-cols-2">
          <div className="bg-background py-4 pr-4">
            <h4 className="text-sm font-medium text-foreground">Pit stops</h4>
            {widget.pit_stops?.length ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {widget.pit_stops.map((stop, index) => {
                  const label = formatPitStop(stop)
                  return label ? <Badge key={index} variant="default">{label}</Badge> : null
                })}
              </div>
            ) : (
              <div className="mt-2 text-sm text-muted-foreground">No stop summary available.</div>
            )}
          </div>

          <div className="bg-background py-4 sm:pl-4">
            <h4 className="text-sm font-medium text-foreground">Race shape</h4>
            <div className="mt-3 space-y-2 text-sm">
              {widget.interval_summary?.latest_gap_to_leader ? (
                <div className="flex justify-between gap-4">
                  <span className="text-muted-foreground">Gap to leader</span>
                  <span className="font-mono-data text-foreground">{widget.interval_summary.latest_gap_to_leader}</span>
                </div>
              ) : null}
              {widget.interval_summary?.latest_interval ? (
                <div className="flex justify-between gap-4">
                  <span className="text-muted-foreground">Interval</span>
                  <span className="font-mono-data text-foreground">{widget.interval_summary.latest_interval}</span>
                </div>
              ) : null}
              {widget.position_timeline_summary?.earliest_sample_position && widget.position_timeline_summary?.latest_position ? (
                <div className="flex justify-between gap-4">
                  <span className="text-muted-foreground">Position arc</span>
                  <span className="font-mono-data text-foreground">
                    P{widget.position_timeline_summary.earliest_sample_position} to P{widget.position_timeline_summary.latest_position}
                  </span>
                </div>
              ) : null}
            </div>
          </div>
        </section>

        {widget.radio_highlights?.length ? (
          <section className="py-4">
            <h4 className="text-sm font-medium text-foreground">Radio</h4>
            <div className="mt-3 divide-y divide-border">
              {widget.radio_highlights.map((msg, index) => (
                <div key={index} className="py-3 first:pt-0 last:pb-0">
                  <div className="mb-1 flex items-center justify-between gap-3">
                    <span className="font-mono-data text-xs text-muted-foreground">{formatRadioTime(msg.date)}</span>
                    {msg.recording_url ? (
                      <a href={msg.recording_url} target="_blank" rel="noreferrer" className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground">
                        clip
                      </a>
                    ) : null}
                  </div>
                  <div className="text-sm leading-6 text-foreground">{msg.message ? `"${msg.message}"` : 'Audio only'}</div>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        {widget.rivalry_story?.length ? (
          <section className="py-4">
            <h4 className="text-sm font-medium text-foreground">On-track battles</h4>
            <ul className="mt-3 space-y-2 text-sm leading-6 text-foreground">
              {widget.rivalry_story.map((item, index) => <li key={index}>{item}</li>)}
            </ul>
          </section>
        ) : null}
      </div>
    </div>
  )
}
