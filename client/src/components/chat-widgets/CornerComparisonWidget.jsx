import { Badge } from '../ui/badge.jsx'

function fmt(value, suffix = ' kph') {
  return typeof value === 'number' ? `${Math.abs(value).toFixed(1)}${suffix}` : '-'
}

const SETUP_LABELS = {
  corner_heavy: 'Corner-heavy',
  straight_heavy: 'Straight-line',
  balanced: 'Balanced',
}

const CAUSE_LABELS = {
  braking: 'Braking',
  minimum_speed: 'Minimum speed',
  traction: 'Traction',
  mixed: 'Mixed',
  none: 'Mixed',
}

export default function CornerComparisonWidget({ widget }) {
  const driverA = widget.driver_a
  const driverB = widget.driver_b

  return (
    <div className="widget-enter max-w-3xl overflow-hidden border-y border-border/80 py-1">
      <div className="grid gap-px bg-border/70 sm:grid-cols-[1fr_8rem_1fr]">
        <div className="bg-background py-4 pr-4">
          <div className="text-sm text-muted-foreground">{driverA}</div>
          <div className="mt-1 font-mono-data text-2xl font-semibold text-foreground">
            {fmt(widget.avg_straight_speed_a_kph)}
          </div>
        </div>
        <div className="bg-background py-4 sm:text-center">
          <div className="text-xs text-muted-foreground">Setup read</div>
          <div className="mt-2 text-sm font-semibold text-foreground">
            {SETUP_LABELS[widget.setup_direction_inference] ?? widget.setup_direction_inference ?? '-'}
          </div>
        </div>
        <div className="bg-background py-4 sm:pl-4 sm:text-right">
          <div className="text-sm text-muted-foreground">{driverB}</div>
          <div className="mt-1 font-mono-data text-2xl font-semibold text-foreground">
            {fmt(widget.avg_straight_speed_b_kph)}
          </div>
        </div>
      </div>

      {widget.gain_location_summary?.length ? (
        <section className="py-4">
          <h4 className="text-sm font-medium text-foreground">Corner gain markers</h4>
          <div className="mt-3 divide-y divide-border/70">
            {widget.gain_location_summary.slice(0, 3).map((item, index) => (
              <div key={`${item.corner}-${index}`} className="grid gap-3 py-3 sm:grid-cols-[5.5rem_minmax(0,1fr)]">
                <div>
                  <Badge variant={index === 0 ? 'accent' : 'muted'}>{item.corner}</Badge>
                </div>
                <div>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-sm font-medium text-foreground">
                      {CAUSE_LABELS[item.cause] ?? item.cause ?? 'Mixed'}
                    </div>
                    <div className="font-mono-data text-xs text-muted-foreground">
                      apex {fmt(item.apex_delta_kph)} / exit {fmt(item.exit_delta_kph)}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {widget.cause_breakdown && Object.keys(widget.cause_breakdown).length ? (
        <section className="border-t border-border py-4">
          <h4 className="text-sm font-medium text-foreground">Pattern count</h4>
          <div className="mt-3 flex flex-wrap gap-2">
            {Object.entries(widget.cause_breakdown).map(([cause, count]) => (
              <Badge key={cause} variant="default">
                {CAUSE_LABELS[cause] ?? cause}: {count}
              </Badge>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  )
}
