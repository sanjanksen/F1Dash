import { Badge } from '../ui/badge.jsx'
import { formatTimeDelta } from './formatTimeDelta.js'

function fmtSecs(n) {
  return typeof n === 'number' ? `${n.toFixed(2)}s` : '-'
}

function fmtKph(n) {
  return typeof n === 'number' ? `${n.toFixed(0)} kph` : '-'
}

export default function ActiveAeroWidget({ widget }) {
  if (!widget) return null

  if (!widget.circuit_in_coverage) {
    return (
      <section className="widget-enter max-w-3xl rounded-md border border-border/80 bg-muted/40 px-4 py-3 text-sm text-muted-foreground">
        Active-aero zone coverage is not yet defined for this circuit; can't surface Z-mode usage here.
      </section>
    )
  }

  const segments = widget.segments ?? []
  const totalZ = widget.total_z_mode_seconds ?? 0
  const delta = widget.estimated_lap_time_delta_s ?? 0

  // Per-segment time estimate is a pro-rated share of the lap-time delta by Z-mode duration.
  const segmentTimeEstimate = (seg) => {
    if (!delta || !totalZ || !seg?.duration_s) return null
    return -(delta / totalZ) * seg.duration_s
  }

  return (
    <section className="widget-enter max-w-3xl space-y-3 border-y border-border/80 py-4">
      <header className="flex items-center justify-between gap-2">
        <div className="text-sm">
          <span className="font-semibold text-foreground">Active aero</span>
          <span className="text-muted-foreground">
            {' '}— {widget.driver_code ?? 'driver'}, lap {widget.lap_number ?? '-'}
          </span>
        </div>
        {widget.inferred ? (
          <Badge
            variant="muted"
            className="tracking-[0.08em]"
            title="Inferred from speed-trace shape — FastF1 did not expose an active-aero channel."
          >
            inferred
          </Badge>
        ) : (
          <Badge variant="default" className="tracking-[0.08em]">measured</Badge>
        )}
      </header>

      <dl className="grid grid-cols-2 gap-4 text-sm">
        <div>
          <dt className="text-xs uppercase tracking-wide text-muted-foreground">Total Z-mode</dt>
          <dd className="mt-1 font-mono-data text-lg font-semibold text-foreground">
            {fmtSecs(totalZ)}
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-muted-foreground">Est. lap-time vs X-only</dt>
          <dd className="mt-1 font-mono-data text-lg font-semibold text-foreground">
            -{fmtSecs(delta)}
          </dd>
        </div>
      </dl>

      {segments.length > 0 ? (
        <ul className="space-y-1 text-sm">
          {segments.map((seg, i) => {
            const segTime = segmentTimeEstimate(seg)
            const segTimeStr = formatTimeDelta(segTime, { approximate: true })
            return (
              <li
                key={i}
                className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-3 border-t border-border/60 py-2 first:border-t-0"
              >
                <span className="text-foreground">{seg.label || 'unlabelled zone'}</span>
                <span className="font-mono-data text-foreground">{segTimeStr ?? '—'}</span>
                <span className="font-mono-data text-muted-foreground">{fmtSecs(seg.duration_s)}</span>
                <span className="font-mono-data text-muted-foreground">{fmtKph(seg.peak_speed_kph)}</span>
              </li>
            )
          })}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">No Z-mode segments detected on this lap.</p>
      )}
    </section>
  )
}
