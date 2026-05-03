import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import SpeedTraceChart from './SpeedTraceChart.jsx'
import TrackMap from './TrackMap.jsx'
import { Badge } from '../ui/badge.jsx'

const COLOR_A = 'hsl(var(--primary))'
const COLOR_B = 'hsl(var(--speed))'

const RANK_META = [
  { label: 'Primary', short: 'P', className: 'text-primary' },
  { label: 'Secondary', short: 'S', className: 'text-[hsl(var(--time))]' },
  { label: 'Tertiary', short: 'T', className: 'text-foreground' },
]

const CAUSE_LABELS = {
  braking: 'Braking',
  minimum_speed: 'Min speed',
  traction: 'Traction',
  straight_line_speed: 'Straight speed',
  straight_line_speed_energy_limited: 'Straight speed, ERS',
  mixed: 'Mixed',
}

const CAUSE_DESC = {
  braking: (winner, loser, delta, dist) =>
    `${winner} trailed the braking point while ${loser} committed earlier${dist}, carrying ${delta ? `${delta} more` : 'more'} entry speed.`,
  minimum_speed: (winner, loser, delta, dist) =>
    `${winner} carried a cleaner arc through the direction change${dist}${delta ? ` — ${delta} faster at the apex` : ''}.`,
  traction: (winner, loser, delta, dist) =>
    `${winner} got the power down sooner on exit${dist}${delta ? `, opening a ${delta} gap onto the straight` : ''}.`,
  straight_line_speed: (winner, loser, delta, dist) =>
    `${winner} was ${delta ? `${delta} quicker` : 'faster'} in a committed straight-line run${dist} — setup trim or DRS timing.`,
  straight_line_speed_energy_limited: (winner, loser, delta, dist) =>
    `${winner} stayed flat while ${loser} faded${dist} — an ERS deployment difference, not aero.`,
  mixed: (winner, loser, delta, dist) =>
    `${winner} was ${delta ? `${delta} ahead` : 'faster'}${dist} through a combination of factors.`,
}

CAUSE_DESC.minimum_speed = (winner, loser, delta, loc) =>
  `${winner} carried more speed ${loc || 'through the corner'}${delta ? ` - ${delta} faster at the apex` : ''}.`
CAUSE_DESC.traction = (winner, loser, delta, loc) =>
  `${winner} got the power down sooner ${loc || 'on corner exit'}${delta ? `, opening a ${delta} gap onto the following straight` : ''}.`
CAUSE_DESC.straight_line_speed = (winner, loser, delta, loc) =>
  `${winner} was ${delta ? `${delta} quicker` : 'faster'} ${loc || 'on the straight'} - likely setup trim, DRS timing, or deployment.`
CAUSE_DESC.straight_line_speed_energy_limited = (winner, loser, delta, loc) =>
  `${winner} kept accelerating while ${loser} faded ${loc || 'late on the straight'} - an ERS deployment difference.`
CAUSE_DESC.mixed = (winner, loser, delta, loc) =>
  `${winner} was ${delta ? `${delta} ahead` : 'faster'} ${loc || 'in this part of the lap'} through a combination of factors.`

function formatTime(t) {
  if (!t) return '-'
  return t.replace('0:', '')
}

function formatGap(v) {
  if (typeof v !== 'number') return null
  return `${Math.abs(v).toFixed(3)}s`
}

function formatPct(v) {
  return typeof v === 'number' ? `${v.toFixed(1)}%` : '-'
}

function formatCount(v) {
  return typeof v === 'number' ? v.toFixed(1) : '-'
}

function normalizeCause(cause, index) {
  if (!cause) return null
  const rankIndex = Math.max(0, Math.min((cause.rank ?? index + 1) - 1, RANK_META.length - 1))
  const meta = RANK_META[rankIndex]
  return {
    ...cause,
    rankIndex,
    rankLabel: meta.label,
    rankShort: meta.short,
    rankClassName: meta.className,
  }
}

function traceCoversCauses(points, causes) {
  if (!points?.length || !causes?.length) return true
  const distances = points
    .map((point) => point.distance_m)
    .filter((value) => typeof value === 'number')
  if (distances.length === 0) return false
  const min = Math.min(...distances)
  const max = Math.max(...distances)
  return causes.every((cause) =>
    typeof cause.distance_m !== 'number' || (cause.distance_m >= min && cause.distance_m <= max)
  )
}

function causeWinner(cause, driverA, driverB, fasterDriver) {
  if (typeof cause.delta_speed_kph === 'number') {
    if (cause.delta_speed_kph > 0) return driverA
    if (cause.delta_speed_kph < 0) return driverB
  }
  return fasterDriver ?? driverA
}

function locationLabel(cause) {
  return cause.location_context?.label ?? (cause.distance_m != null ? `${cause.distance_m}m` : 'distance n/a')
}

function locationPlain(cause) {
  return cause.location_context?.plain ?? (typeof cause.distance_m === 'number' ? `at ${cause.distance_m}m` : '')
}

function causeDescription(cause, driverA, driverB, fasterDriver) {
  const winner = causeWinner(cause, driverA, driverB, fasterDriver)
  const loser = winner === driverA ? driverB : driverA
  const delta = typeof cause.delta_speed_kph === 'number'
    ? `${Math.abs(cause.delta_speed_kph).toFixed(1)} kph`
    : null
  const dist = locationPlain(cause)
  const fn = CAUSE_DESC[cause.cause_type] ?? CAUSE_DESC.mixed
  return fn(winner, loser, delta, dist ? ` ${dist}` : '').replace(/\s+/g, ' ')
}

function SectorBar({ label, sectorData, maxAbsGap, driverA, driverB }) {
  if (!sectorData) return null
  const gap = sectorData.gap_s
  const aFaster = typeof gap === 'number' && gap < 0
  const bFaster = typeof gap === 'number' && gap > 0
  const width = typeof gap === 'number' && maxAbsGap > 0
    ? Math.max(6, (Math.abs(gap) / maxAbsGap) * 100)
    : 0

  return (
    <div className="grid grid-cols-[2.25rem_minmax(0,1fr)_6.5rem] items-center gap-3">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className="h-2 overflow-hidden rounded-sm bg-secondary">
        <div
          className="h-full rounded-sm transition-[width] duration-300"
          style={{
            width: `${width}%`,
            marginLeft: bFaster ? `${100 - width}%` : 0,
            background: aFaster ? COLOR_A : bFaster ? COLOR_B : 'hsl(var(--muted-foreground))',
          }}
        />
      </div>
      <div className="text-right text-xs font-medium text-foreground">
        {aFaster || bFaster ? `${aFaster ? driverA : driverB} +${formatGap(gap)}` : 'Level'}
      </div>
    </div>
  )
}

function MechanismRow({ cause, active, driverA, driverB, fasterDriver, onMouseEnter, onMouseLeave }) {
  const { cause_type, delta_speed_kph, explanation } = cause
  const winnerDelta = typeof delta_speed_kph === 'number' ? `${Math.abs(delta_speed_kph).toFixed(1)} kph` : '-'
  const mechanism = CAUSE_LABELS[cause_type] ?? cause_type ?? 'Mixed'
  const description = causeDescription(cause, driverA, driverB, fasterDriver)

  return (
    <div
      className={active ? 'rounded-lg bg-secondary px-3 py-3' : 'rounded-lg px-3 py-3'}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <div className="grid gap-3 sm:grid-cols-[7.5rem_minmax(0,1fr)]">
        <div>
          <div className={`text-sm font-semibold ${cause.rankClassName}`}>{cause.rankLabel}</div>
          <div className="mt-0.5 font-mono-data text-xs text-muted-foreground">
            {locationLabel(cause)}
          </div>
        </div>
        <div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-sm font-medium text-foreground">{mechanism}</div>
            <div className="font-mono-data text-xs text-muted-foreground">{winnerDelta}</div>
          </div>
          <div className="mt-2 text-sm leading-6 text-muted-foreground">{description}</div>
          {explanation ? <div className="mt-2 text-xs leading-5 text-muted-foreground/80">{explanation}</div> : null}
        </div>
      </div>
    </div>
  )
}

function StylePanel({ style, driverA, driverB }) {
  const a = style?.driver_a_style ?? style?.driver_a
  const b = style?.driver_b_style ?? style?.driver_b
  const prediction = style?.style_prediction
  if (!a && !b && !prediction) return null

  return (
    <section className="border-t border-border py-4">
      <h4 className="text-sm font-medium text-foreground">Driving style</h4>
      {(a || b) && (
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          {[{ code: driverA, profile: a }, { code: driverB, profile: b }].map(({ code, profile }) => (
            profile ? (
              <div key={code}>
                <div className="mb-2 flex items-center gap-2">
                  <Badge variant="muted">{code}</Badge>
                  <span className="text-xs text-muted-foreground">
                    {profile.corner_approach?.replace('_', '-')} / {profile.steering_style}
                  </span>
                </div>
                {profile.key_traits?.slice(0, 2).map((trait, i) => (
                  <div key={i} className="text-xs leading-5 text-muted-foreground">{trait}</div>
                ))}
              </div>
            ) : null
          ))}
        </div>
      )}
      {prediction ? <div className="mt-3 text-sm leading-6 text-foreground">{prediction}</div> : null}
    </section>
  )
}

function formatRowVal(val, fmt) {
  if (val == null) return '—'
  if (fmt === 'pct') return `${Number(val).toFixed(1)}%`
  if (fmt === 'count') return Number(val).toFixed(1)
  if (fmt === 'raw3') return Number(val).toFixed(3)
  return String(val)
}

const SECTION_META = {
  commitment: {
    label: 'Commitment',
    sub: 'how hard they asked the car',
    headerClass: 'bg-primary/8 border-primary/20',
    labelClass: 'text-primary',
  },
  technique: {
    label: 'Technique',
    sub: 'the flip side — how cleanly they executed',
    headerClass: 'bg-muted/40 border-border/50',
    labelClass: 'text-foreground',
  },
}

function CornerAnalysisPanel({ grip, driverA, driverB }) {
  if (!grip) return null

  const committed = grip.more_committed_driver
  const cleaner   = grip.cleaner_driver

  const commitmentRows = (grip.data_rows || []).filter((r) => r.group === 'commitment')
  const techniqueRows  = (grip.data_rows || []).filter((r) => r.group === 'technique')

  const groups = [
    { key: 'commitment', rows: commitmentRows },
    { key: 'technique',  rows: techniqueRows  },
  ].filter((g) => g.rows.length > 0)

  return (
    <section className="py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h4 className="text-sm font-medium text-foreground">Corner analysis</h4>
        <div className="text-xs text-muted-foreground">From cornering load data</div>
      </div>

      {grip.confidence_read ? (
        <div className="mt-2 text-sm leading-6 text-muted-foreground">{grip.confidence_read}</div>
      ) : null}

      {/* Driver summary badges */}
      <div className="mt-3 flex flex-wrap gap-4">
        {[driverA, driverB].map((code) => (
          <div key={code} className="flex items-center gap-2">
            <Badge variant={committed === code ? 'accent' : 'muted'}>{code}</Badge>
            {committed === code && cleaner !== code ? <span className="text-xs text-muted-foreground">more committed</span> : null}
            {cleaner === code && committed !== code ? <span className="text-xs text-muted-foreground">cleaner arc</span> : null}
            {cleaner === code && committed === code ? <span className="text-xs text-muted-foreground">committed + clean</span> : null}
            {cleaner !== code && committed !== code ? <span className="text-xs text-muted-foreground/60">—</span> : null}
          </div>
        ))}
      </div>

      {/* Two distinct boxed sections */}
      {groups.length > 0 && (
        <div className="mt-4 space-y-3">
          {groups.map(({ key, rows }) => {
            const meta = SECTION_META[key]
            return (
              <div key={key} className={`rounded-lg border overflow-hidden ${meta.headerClass}`}>
                {/* Section header band */}
                <div className={`flex items-baseline gap-2 px-3 py-2 border-b ${meta.headerClass}`}>
                  <span className={`text-xs font-semibold ${meta.labelClass}`}>{meta.label}</span>
                  <span className="text-[10px] text-muted-foreground">{meta.sub}</span>
                </div>
                {/* Data table */}
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-border/30">
                      <th className="px-3 pb-1.5 pt-2 text-left text-[10px] font-normal text-muted-foreground w-[44%]">Metric</th>
                      <th className="pb-1.5 pt-2 pr-2 text-right text-[10px] font-normal text-muted-foreground">{driverA}</th>
                      <th className="pb-1.5 pt-2 pr-2 text-right text-[10px] font-normal text-muted-foreground">{driverB}</th>
                      <th className="pb-1.5 pt-2 pr-3 text-right text-[10px] font-normal text-muted-foreground">Edge</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, i) => (
                      <tr key={i} className="border-b border-border/15 last:border-0">
                        <td className="px-3 py-1.5 text-[11px] text-muted-foreground">{row.label}</td>
                        <td className={`py-1.5 pr-2 text-right font-mono text-xs tabular-nums ${row.edge === driverA ? 'font-semibold text-foreground' : 'text-muted-foreground/70'}`}>
                          {formatRowVal(row.a, row.format)}
                        </td>
                        <td className={`py-1.5 pr-2 text-right font-mono text-xs tabular-nums ${row.edge === driverB ? 'font-semibold text-foreground' : 'text-muted-foreground/70'}`}>
                          {formatRowVal(row.b, row.format)}
                        </td>
                        <td className="py-1.5 pr-3 text-right text-[10px] text-muted-foreground">
                          {row.edge ? `${row.edge} — ${row.edge_label}` : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

export default function QualifyingBattleWidget({ widget }) {
  const [activeMechIndex, setActiveMechIndex] = useState(null)
  const [detailsExpanded, setDetailsExpanded] = useState(true)

  const driverA = widget.driver_a ?? widget.title?.split(' vs ')[0]
  const driverB = widget.driver_b ?? widget.title?.split(' vs ')[1]
  const fasterIsA = widget.faster_driver === driverA

  const lapA = widget.sector_comparison?.lap_time_a
  const lapB = widget.sector_comparison?.lap_time_b
  const s1 = widget.sector_comparison?.sector1
  const s2 = widget.sector_comparison?.sector2
  const s3 = widget.sector_comparison?.sector3
  const gapValues = [s1?.gap_s, s2?.gap_s, s3?.gap_s].filter((v) => typeof v === 'number')
  const maxAbsGap = Math.max(...gapValues.map(Math.abs), 0.001)
  const topCauses = (widget.cause_explanations?.length
    ? widget.cause_explanations
    : widget.cause_type || widget.cause_explanation
      ? [{
          cause_type: widget.cause_type,
          rank: 1,
          distance_m: null,
          delta_speed_kph: null,
          explanation: widget.cause_explanation,
        }]
      : []
  ).map(normalizeCause).filter(Boolean)
  const tracePoints = traceCoversCauses(widget.focus_window_trace, topCauses)
    ? (widget.focus_window_trace?.length ? widget.focus_window_trace : widget.speed_trace)
    : widget.speed_trace
  const energyAlreadyExplained = topCauses.some((cause) => cause.cause_type === 'straight_line_speed_energy_limited')
  const hasDetails = Boolean(
    tracePoints?.length ||
    widget.zone_summary ||
    topCauses.length ||
    (widget.energy_relevant && widget.energy_reason && !energyAlreadyExplained) ||
    widget.grip_commitment ||
    widget.style_comparison,
  )

  return (
    <div className="widget-enter max-w-3xl overflow-hidden border-y border-border/80 py-1">
      <div className="grid gap-px bg-border/70 sm:grid-cols-[1fr_7rem_1fr]">
        <div className="bg-background py-4 pr-4">
          <div className="text-sm text-muted-foreground">{driverA}</div>
          <div className="mt-1 font-mono-data text-2xl font-semibold text-foreground">{formatTime(lapA)}</div>
          {fasterIsA ? <Badge variant="accent" className="mt-2">Faster</Badge> : null}
        </div>
        <div className="bg-background py-4 sm:text-center">
          <div className="text-xs text-muted-foreground">Gap</div>
          <div className="mt-2 font-mono-data text-lg font-semibold text-foreground">
            {formatGap(widget.overall_gap_s) ?? '-'}
          </div>
        </div>
        <div className="bg-background py-4 sm:pl-4 sm:text-right">
          <div className="text-sm text-muted-foreground">{driverB}</div>
          <div className="mt-1 font-mono-data text-2xl font-semibold text-foreground">{formatTime(lapB)}</div>
          {!fasterIsA ? <Badge variant="accent" className="mt-2">Faster</Badge> : null}
        </div>
      </div>

      <div className="divide-y divide-border">
        {widget.is_teammate_comparison ? (
          <div className="py-4 text-sm leading-6 text-muted-foreground">
            {widget.teammate_context ?? 'Same team, so the comparison is more about driving style and setup than car performance.'}
          </div>
        ) : null}

        {(s1 || s2 || s3) && (
          <section className="py-4">
            <h4 className="text-sm font-medium text-foreground">Sector breakdown</h4>
            <div className="mt-3 space-y-3">
              {[
                ['S1', s1],
                ['S2', s2],
                ['S3', s3],
              ].filter(([, data]) => data).map(([label, data]) => (
                <SectorBar
                  key={label}
                  label={label}
                  sectorData={data}
                  maxAbsGap={maxAbsGap}
                  driverA={driverA}
                  driverB={driverB}
                />
              ))}
            </div>
          </section>
        )}

        {hasDetails ? (
          <section className="py-3">
            <button
              type="button"
              className="flex w-full items-center justify-between gap-3 rounded-md px-1 py-1 text-left text-sm font-medium text-foreground hover:text-primary focus:outline-none focus:ring-2 focus:ring-ring"
              aria-expanded={detailsExpanded}
              onClick={() => setDetailsExpanded((value) => !value)}
            >
              <span>Telemetry detail</span>
              <span className="flex items-center gap-2 text-xs text-muted-foreground">
                {detailsExpanded ? 'Hide' : 'Show'}
                <ChevronDown className={detailsExpanded ? 'h-4 w-4 transition-transform duration-200' : 'h-4 w-4 -rotate-90 transition-transform duration-200'} />
              </span>
            </button>
          </section>
        ) : null}

        {hasDetails ? (
          <div
            className="grid transition-[grid-template-rows,opacity] duration-200 ease-out"
            style={{
              gridTemplateRows: detailsExpanded ? '1fr' : '0fr',
              opacity: detailsExpanded ? 1 : 0,
            }}
          >
            <div className="min-h-0 overflow-hidden">
              <div className="divide-y divide-border">
                {tracePoints?.length ? (
                  <section className="py-4">
                    <div className={widget.track_map?.length ? 'grid gap-4 lg:grid-cols-[minmax(0,1fr)_16rem]' : ''}>
                      <SpeedTraceChart
                        points={tracePoints}
                        driverA={driverA}
                        driverB={driverB}
                        decisiveDistance={null}
                        decisiveCorner={widget.decisive_corner}
                        causes={topCauses}
                        activeMechIndex={activeMechIndex}
                        onMechHover={setActiveMechIndex}
                      />
                      {widget.track_map?.length ? (
                        <TrackMap
                          points={widget.track_map}
                          causes={topCauses}
                          activeMechIndex={activeMechIndex}
                          onMechHover={setActiveMechIndex}
                        />
                      ) : null}
                    </div>
                  </section>
                ) : null}

                {widget.zone_summary ? (
                  <div className="py-4 text-sm leading-6 text-muted-foreground">{widget.zone_summary}</div>
                ) : null}

                {topCauses.length > 0 && (
                  <section className="py-4">
                    <div className="flex flex-wrap items-baseline justify-between gap-3">
                      <h4 className="text-sm font-medium text-foreground">P/S/T marker details</h4>
                      <div className="text-xs text-muted-foreground">Same points as the trace and map</div>
                    </div>
                    <div className="mt-3 divide-y divide-border/70">
                      {topCauses.map((cause, i) => (
                        <MechanismRow
                          key={`${cause.rankLabel}-${cause.cause_type}-${i}`}
                          cause={cause}
                          active={activeMechIndex === i}
                          driverA={driverA}
                          driverB={driverB}
                          fasterDriver={widget.faster_driver}
                          onMouseEnter={() => setActiveMechIndex(i)}
                          onMouseLeave={() => setActiveMechIndex(null)}
                        />
                      ))}
                    </div>
                  </section>
                )}

                {topCauses.length === 0 && widget.cause_explanation ? (
                  <div className="py-4 text-sm leading-6 text-muted-foreground">{widget.cause_explanation}</div>
                ) : null}

                {widget.energy_relevant && widget.energy_reason && !energyAlreadyExplained ? (
                  <div className="py-4 text-sm leading-6 text-muted-foreground">{widget.energy_reason}</div>
                ) : null}

                {widget.grip_commitment ? (
                  <CornerAnalysisPanel grip={widget.grip_commitment} driverA={driverA} driverB={driverB} />
                ) : null}

                {widget.style_comparison ? <StylePanel style={widget.style_comparison} driverA={driverA} driverB={driverB} /> : null}
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}
