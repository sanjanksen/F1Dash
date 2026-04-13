import { Badge } from '../ui/badge.jsx'
import { Card, CardContent } from '../ui/card.jsx'

function formatPitStop(stop) {
  const lap = stop?.pit_window_after_lap
  const compound = stop?.new_compound
  if (lap == null && !compound) return null
  return `Lap ${lap ?? '—'}${compound ? ` → ${compound}` : ''}`
}

export default function RaceStoryWidget({ widget }) {
  return (
    <div className="max-w-3xl">
      <Card>
        <CardContent className="space-y-4 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                Driver Race Story
              </div>
              <div className="mt-1 flex items-center gap-2 text-base font-semibold tracking-[-0.02em] text-foreground">
                <span>{widget.title}</span>
                {widget.driver_code ? <Badge variant="muted">{widget.driver_code}</Badge> : null}
              </div>
              <div className="mt-1 text-sm text-muted-foreground">
                {widget.subtitle}{widget.team ? ` · ${widget.team}` : ''}
              </div>
            </div>
            {widget.finish_position ? <Badge variant="default">P{widget.finish_position}</Badge> : null}
          </div>

          <div className="grid gap-3 sm:grid-cols-4">
            <div className="rounded-md border border-border/90 px-3 py-3">
              <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">Grid</div>
              <div className="mt-1 text-lg font-semibold text-foreground">{widget.grid_position ? `P${widget.grid_position}` : '—'}</div>
            </div>
            <div className="rounded-md border border-border/90 px-3 py-3">
              <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">Finish</div>
              <div className="mt-1 text-lg font-semibold text-foreground">{widget.finish_position ? `P${widget.finish_position}` : '—'}</div>
            </div>
            <div className="rounded-md border border-border/90 px-3 py-3">
              <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">Points</div>
              <div className="mt-1 text-lg font-semibold text-foreground">{widget.points ?? '—'}</div>
            </div>
            <div className="rounded-md border border-border/90 px-3 py-3">
              <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">Status</div>
              <div className="mt-1 text-sm font-medium text-foreground">{widget.status ?? '—'}</div>
            </div>
          </div>

          {widget.story_points?.length ? (
            <div className="rounded-md border border-border/90 px-3 py-3">
              <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">Story Line</div>
              <ul className="mt-2 space-y-2 pl-5 text-sm leading-6 text-foreground list-disc">
                {widget.story_points.slice(0, 4).map((point, index) => (
                  <li key={index}>{point}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-md border border-border/90 px-3 py-3">
              <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">Pit Stops</div>
              {widget.pit_stops?.length ? (
                <div className="mt-2 flex flex-wrap gap-2">
                  {widget.pit_stops.map((stop, index) => (
                    <Badge key={index} variant="muted">{formatPitStop(stop)}</Badge>
                  ))}
                </div>
              ) : (
                <div className="mt-1 text-sm text-muted-foreground">No stop summary available.</div>
              )}
            </div>

            <div className="rounded-md border border-border/90 px-3 py-3">
              <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">Race Shape</div>
              <div className="mt-1 space-y-1 text-sm leading-6 text-foreground">
                {widget.interval_summary?.latest_gap_to_leader ? <div>Gap to leader: {widget.interval_summary.latest_gap_to_leader}</div> : null}
                {widget.interval_summary?.latest_interval ? <div>Latest interval: {widget.interval_summary.latest_interval}</div> : null}
                {widget.position_timeline_summary?.earliest_sample_position && widget.position_timeline_summary?.latest_position ? (
                  <div>
                    Position samples: P{widget.position_timeline_summary.earliest_sample_position} → P{widget.position_timeline_summary.latest_position}
                  </div>
                ) : null}
              </div>
            </div>
          </div>

          {widget.radio_highlights?.length ? (
            <div className="rounded-md border border-border/90 px-3 py-3">
              <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">Radio Highlights</div>
              <ul className="mt-2 space-y-2 text-sm leading-6 text-foreground">
                {widget.radio_highlights.map((message, index) => (
                  <li key={index} className="border-t border-border/80 pt-2 first:border-t-0 first:pt-0">
                    <div className="text-xs text-muted-foreground">{message.date ?? 'Radio'}</div>
                    {message.recording_url ? (
                      <a href={message.recording_url} target="_blank" rel="noreferrer" className="text-foreground underline underline-offset-4">
                        Open clip
                      </a>
                    ) : (
                      <span>Radio clip available</span>
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
