import { Badge } from '../ui/badge.jsx'

function fmtSec(n, { signed = false } = {}) {
  if (typeof n !== 'number' || Number.isNaN(n)) return '-'
  const fixed = Math.abs(n) >= 10 ? n.toFixed(1) : n.toFixed(2)
  if (signed && n > 0) return `+${fixed} s`
  return `${fixed} s`
}

const RECOMMENDATION_STYLE = {
  pit_now: { label: 'PIT NOW', cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40' },
  stay_out: { label: 'STAY OUT', cls: 'bg-rose-500/15 text-rose-300 border-rose-500/40' },
  marginal: { label: 'MARGINAL', cls: 'bg-amber-500/15 text-amber-300 border-amber-500/40' },
}

const CONFIDENCE_STYLE = {
  high: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
  moderate: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
  low: 'bg-rose-500/10 text-rose-300 border-rose-500/30',
}

function RecommendationPill({ recommendation }) {
  const style = RECOMMENDATION_STYLE[recommendation] ?? RECOMMENDATION_STYLE.marginal
  return (
    <span className={`inline-flex items-center rounded-md border px-2.5 py-1 text-xs font-semibold tracking-[0.08em] ${style.cls}`}>
      {style.label}
    </span>
  )
}

function ConfidenceChip({ confidence }) {
  const cls = CONFIDENCE_STYLE[confidence] ?? CONFIDENCE_STYLE.moderate
  return (
    <span className={`inline-flex items-center rounded-sm border px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.08em] ${cls}`}>
      confidence: {confidence ?? 'unknown'}
    </span>
  )
}

function BreakdownRow({ label, value, signed = false, emphasis = false }) {
  return (
    <div className={`grid grid-cols-[1fr_auto] items-center gap-3 border-t border-border/60 py-2 first:border-t-0 ${emphasis ? 'font-semibold text-foreground' : 'text-muted-foreground'}`}>
      <span>{label}</span>
      <span className="font-mono-data">{fmtSec(value, { signed })}</span>
    </div>
  )
}

function crossoverLine(crossoverLap, advantageS) {
  if (crossoverLap == null) {
    return 'Stint likely ends before the undercut pays back.'
  }
  if (crossoverLap <= 1) {
    return 'Pays back this cycle (≤1 lap).'
  }
  return `Would pay back at lap ${crossoverLap} of the rejoin window.`
}

export default function UndercutOvercutWidget({ widget }) {
  if (!widget) return null

  const advantage = widget.advantage_s ?? 0
  const advantageColor = advantage > 0 ? 'text-emerald-400' : advantage < 0 ? 'text-rose-400' : 'text-foreground'

  const freshGain = (widget.delta_fresh_pace_s_per_lap ?? 0) * 1  // N=1
  const pitLoss = widget.pit_loss_s ?? 0
  const outLap = widget.out_lap_warmup_s ?? 0
  const traffic = widget.traffic_cost_s ?? 0

  const subline = widget.target_driver_code
    ? `vs ${widget.target_driver_code}`
    : null

  return (
    <section className="widget-enter max-w-3xl space-y-3 border-y border-border/80 py-4">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-sm">
          <span className="font-semibold text-foreground">Undercut analysis</span>
          <span className="text-muted-foreground">
            {' '}— {widget.driver_code ?? 'driver'}, lap {widget.current_lap ?? '-'}
            {subline ? ` (${subline})` : ''}
          </span>
        </div>
        <RecommendationPill recommendation={widget.recommendation} />
      </header>

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-xs uppercase tracking-wide text-muted-foreground">Net advantage</div>
          <div className={`mt-1 font-mono-data text-3xl font-semibold ${advantageColor}`}>
            {fmtSec(advantage, { signed: true })}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <ConfidenceChip confidence={widget.confidence} />
          {widget.active_sc_state && widget.active_sc_state !== 'green' ? (
            <Badge variant="muted" className="tracking-[0.08em]">
              {String(widget.active_sc_state).toUpperCase()} active — pit-loss reduced
            </Badge>
          ) : null}
        </div>
      </div>

      <div className="rounded-md border border-border/70 bg-muted/20 px-3 py-2 text-sm">
        <BreakdownRow label="Fresh-tyre gain (× 1 lap)" value={freshGain} signed />
        <BreakdownRow label="Pit loss" value={-pitLoss} />
        <BreakdownRow label="Out-lap warm-up" value={-outLap} />
        <BreakdownRow label="Traffic cost" value={-traffic} />
        <BreakdownRow label="Net advantage" value={advantage} signed emphasis />
      </div>

      <p className="text-sm text-muted-foreground">{crossoverLine(widget.crossover_lap, advantage)}</p>

      {Array.isArray(widget.rationale) && widget.rationale.length > 0 ? (
        <ul className="space-y-1 text-sm text-foreground">
          {widget.rationale.map((bullet, i) => (
            <li key={i} className="border-l-2 border-border/60 pl-3">
              {bullet}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}
