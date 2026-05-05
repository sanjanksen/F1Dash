import { Badge } from '../ui/badge.jsx'

function fmt(value, suffix = 's') {
  return typeof value === 'number' ? `${Math.abs(value).toFixed(3)}${suffix}` : '-'
}

function fmtDeg(value) {
  return typeof value === 'number' ? `${Math.abs(value).toFixed(3)}s/lap` : '-'
}

function fmtSignedDeg(value) {
  return typeof value === 'number' ? `${value >= 0 ? '+' : ''}${value.toFixed(3)}s/lap` : '-'
}

function fmtSpread(value) {
  return typeof value === 'number' ? `±${value.toFixed(3)}s` : '-'
}

function fmtR2(value) {
  return typeof value === 'number' ? value.toFixed(2) : '-'
}

function winnerFromDelta(delta, driverA, driverB, lowerIsBetter = true) {
  if (typeof delta !== 'number' || delta === 0) return null
  if (lowerIsBetter) return delta < 0 ? driverA : driverB
  return delta > 0 ? driverA : driverB
}

const FACTOR_LABELS = {
  tyre_degradation: 'Tyre degradation',
  raw_pace_advantage: 'Raw pace',
  strategy_execution: 'Strategy execution',
  mixed: 'Mixed',
}

const COMPOUND_ORDER = ['SOFT', 'MEDIUM', 'HARD', 'INTERMEDIATE', 'WET']

function TyreDegTable({ driverA, driverB, tyreA, tyreB }) {
  const compoundsA = Object.keys(tyreA?.per_compound ?? {})
  const compoundsB = Object.keys(tyreB?.per_compound ?? {})
  const compounds = COMPOUND_ORDER.filter(
    (c) => compoundsA.includes(c) || compoundsB.includes(c),
  )
  if (!compounds.length) return null

  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-y border-border/70 text-muted-foreground">
            <th className="py-2 pr-4 text-left font-medium">Driver</th>
            {compounds.map((c) => (
              <>
                <th key={`${c}-rate`} className="px-3 py-2 text-right font-medium">
                  {c.charAt(0) + c.slice(1).toLowerCase()} /lap
                </th>
                <th key={`${c}-total`} className="px-3 py-2 text-right font-medium text-muted-foreground/70">
                  Total lost
                </th>
                <th key={`${c}-laps`} className="px-3 py-2 text-right font-medium text-muted-foreground/70">
                  Laps
                </th>
              </>
            ))}
          </tr>
        </thead>
        <tbody>
          {[[driverA, tyreA], [driverB, tyreB]].map(([driver, tyre]) => (
            <tr key={driver} className="border-b border-border/60 last:border-b-0">
              <td className="py-3 pr-4 font-medium text-foreground">{driver}</td>
              {compounds.map((c) => {
                const stint = tyre?.per_compound?.[c]
                const rate = stint?.positive_deg_rate_s_per_lap
                const total = stint?.total_deg_loss_s
                const laps = stint?.lap_count
                return (
                  <>
                    <td key={`${c}-rate`} className="px-3 py-3 text-right font-mono-data text-foreground">
                      {typeof rate === 'number' ? rate.toFixed(3) : '—'}
                    </td>
                    <td key={`${c}-total`} className="px-3 py-3 text-right font-mono-data text-muted-foreground">
                      {typeof total === 'number' ? `${total.toFixed(1)}s` : '—'}
                    </td>
                    <td key={`${c}-laps`} className="px-3 py-3 text-right font-mono-data text-muted-foreground">
                      {typeof laps === 'number' ? laps : '—'}
                    </td>
                  </>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function RacePaceBattleWidget({ widget }) {
  const driverA = widget.driver_a
  const driverB = widget.driver_b
  const paceWinner = winnerFromDelta(widget.overall_pace_delta_s, driverA, driverB)
  const degWinner = winnerFromDelta(widget.deg_rate_delta, driverA, driverB)
  const tyreA = widget.tyre_management_a
  const tyreB = widget.tyre_management_b

  return (
    <div className="widget-enter max-w-3xl overflow-hidden border-y border-border/80 py-1">
      <div className="grid gap-px bg-border/70 sm:grid-cols-[1fr_9rem_1fr]">
        <div className="bg-background py-4 pr-4">
          <div className="text-sm text-muted-foreground">{driverA}</div>
          <div className="mt-1 font-mono-data text-2xl font-semibold text-foreground">
            {fmt(widget.fuel_corrected_pace_a_s)}
          </div>
          {paceWinner === driverA ? <Badge variant="accent" className="mt-2">Pace edge</Badge> : null}
        </div>
        <div className="bg-background py-4 sm:text-center">
          <div className="text-xs text-muted-foreground">Pace delta</div>
          <div className="mt-2 font-mono-data text-lg font-semibold text-foreground">
            {fmt(widget.overall_pace_delta_s)}
          </div>
        </div>
        <div className="bg-background py-4 sm:pl-4 sm:text-right">
          <div className="text-sm text-muted-foreground">{driverB}</div>
          <div className="mt-1 font-mono-data text-2xl font-semibold text-foreground">
            {fmt(widget.fuel_corrected_pace_b_s)}
          </div>
          {paceWinner === driverB ? <Badge variant="accent" className="mt-2">Pace edge</Badge> : null}
        </div>
      </div>

      <div className="divide-y divide-border">
        <section className="grid gap-px bg-border/70 sm:grid-cols-3">
          {[
            ['Decisive factor', FACTOR_LABELS[widget.decisive_factor] ?? widget.decisive_factor ?? '-'],
            ['Deg edge', degWinner ? `${degWinner} by ${fmtDeg(widget.deg_rate_delta)}` : '-'],
            ['Undercut', widget.undercut_opportunity?.note ?? '-'],
          ].map(([label, value]) => (
            <div key={label} className="bg-background py-3 sm:px-4">
              <div className="text-xs text-muted-foreground">{label}</div>
              <div className="mt-1 text-sm font-medium text-foreground">{value}</div>
            </div>
          ))}
        </section>

        {(tyreA?.per_compound || tyreB?.per_compound) ? (
          <section className="py-4">
            <h4 className="text-sm font-medium text-foreground">Tyre degradation</h4>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              Deg rate adds back expected fuel-burn gain — positive values are tyre performance loss per lap. Compare within compound only.
            </p>
            <TyreDegTable driverA={driverA} driverB={driverB} tyreA={tyreA} tyreB={tyreB} />
          </section>
        ) : null}

        {widget.aligned_stints?.length ? (
          <section className="py-4">
            <h4 className="text-sm font-medium text-foreground">Matched stints</h4>
            <div className="mt-3 divide-y divide-border/70">
              {widget.aligned_stints.slice(0, 4).map((stint, index) => (
                <div key={index} className="grid gap-2 py-3 text-sm sm:grid-cols-[5rem_minmax(0,1fr)_7rem]">
                  <div className="text-muted-foreground">{stint.compound ?? `Stint ${index + 1}`}</div>
                  <div className="text-foreground">
                    {driverA}: {fmt(stint.driver_a?.fuel_corrected_pace_at_age_1_s)} / {driverB}: {fmt(stint.driver_b?.fuel_corrected_pace_at_age_1_s)}
                  </div>
                  <div className="font-mono-data text-xs text-muted-foreground sm:text-right">
                    {stint.lap_overlap ? `${stint.lap_overlap} laps` : ''}
                  </div>
                </div>
              ))}
            </div>
          </section>
        ) : null}
      </div>
    </div>
  )
}
