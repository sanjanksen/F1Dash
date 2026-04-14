import SpeedTraceChart from './SpeedTraceChart.jsx'

const COLOR_A = 'hsl(0, 75%, 52%)'
const COLOR_B = 'hsl(186, 100%, 45%)'

const CAUSE_LABELS = {
  braking: 'Braking',
  minimum_speed: 'Min Speed',
  traction: 'Traction',
  straight_line_speed: 'Straight Speed',
  straight_line_speed_energy_limited: 'Str. Speed (ERS)',
  mixed: 'Mixed',
}

const CAUSE_ICONS = {
  braking: '⬛',
  minimum_speed: '⬡',
  traction: '⬤',
  straight_line_speed: '▶',
  straight_line_speed_energy_limited: '⚡',
}

function formatTime(t) {
  if (!t) return '—'
  return t.replace('0:', '')  // strip leading "0:" for short sector times
}

function formatGap(v) {
  if (typeof v !== 'number') return null
  return `${Math.abs(v).toFixed(3)}s`
}

// ── Sector tug-of-war bar ──────────────────────────────────────────────────

function SectorBar({ sectorKey, label, sectorData, maxAbsGap, driverA, driverB, fasterDriver }) {
  if (!sectorData) return null
  const gap = sectorData.gap_s  // negative = A faster
  const timeA = sectorData.time_a
  const timeB = sectorData.time_b

  let aWidth = 50
  if (typeof gap === 'number' && maxAbsGap > 0) {
    // gap < 0 → A faster → a takes more than 50%
    aWidth = 50 + Math.min(Math.abs(gap) / maxAbsGap, 1) * 32 * (gap < 0 ? 1 : -1)
    aWidth = Math.max(18, Math.min(82, aWidth))
  }
  const bWidth = 100 - aWidth

  const aFaster = typeof gap === 'number' && gap < 0
  const bFaster = typeof gap === 'number' && gap > 0
  const level = !aFaster && !bFaster

  return (
    <div className="grid grid-cols-[2rem_minmax(0,1fr)_5.5rem] items-center gap-3">
      {/* Label */}
      <div className="text-[10px] font-semibold uppercase tracking-[0.15em] text-muted-foreground">
        {label}
      </div>

      {/* Bar */}
      <div className="relative h-5 overflow-hidden rounded-sm" style={{ background: 'hsl(0,0%,10%)' }}>
        {/* Driver A side (left) */}
        <div
          className="absolute inset-y-0 left-0 transition-all duration-500"
          style={{
            width: `${aWidth}%`,
            background: aFaster
              ? `linear-gradient(90deg, ${COLOR_A}44, ${COLOR_A}bb)`
              : 'hsl(0,0%,18%)',
            borderRight: aFaster ? `2px solid ${COLOR_A}` : '2px solid hsl(0,0%,25%)',
          }}
        />
        {/* Driver B side (right) */}
        <div
          className="absolute inset-y-0 right-0 transition-all duration-500"
          style={{
            width: `${bWidth}%`,
            background: bFaster
              ? `linear-gradient(90deg, ${COLOR_B}bb, ${COLOR_B}44)`
              : 'hsl(0,0%,18%)',
            borderLeft: bFaster ? `2px solid ${COLOR_B}` : 'none',
          }}
        />
        {/* Driver code overlays */}
        {timeA && (
          <div
            className="absolute inset-y-0 left-0 flex items-center pl-1.5 text-[9px] font-mono-data font-semibold"
            style={{ color: aFaster ? COLOR_A : 'hsl(0,0%,45%)' }}
          >
            {formatTime(timeA)}
          </div>
        )}
        {timeB && (
          <div
            className="absolute inset-y-0 right-0 flex items-center pr-1.5 text-[9px] font-mono-data font-semibold"
            style={{ color: bFaster ? COLOR_B : 'hsl(0,0%,45%)' }}
          >
            {formatTime(timeB)}
          </div>
        )}
      </div>

      {/* Delta */}
      <div className="text-right">
        {level ? (
          <span className="text-[10px] text-muted-foreground">Level</span>
        ) : (
          <span
            className="text-[11px] font-semibold font-mono-data"
            style={{ color: aFaster ? COLOR_A : COLOR_B }}
          >
            {aFaster ? driverA : driverB} +{formatGap(gap)}
          </span>
        )}
      </div>
    </div>
  )
}

// ── Mechanism ranked bar ───────────────────────────────────────────────────

function MechanismRow({ cause, rank, maxMag, driverA, driverB }) {
  const { cause_type, delta_speed_kph, distance_m, explanation } = cause
  const mag = Math.abs(delta_speed_kph ?? 0)
  const barPct = maxMag > 0 ? (mag / maxMag) * 100 : 0
  const aFaster = typeof delta_speed_kph === 'number' && delta_speed_kph > 0
  const winner = aFaster ? driverA : driverB
  const winColor = aFaster ? COLOR_A : COLOR_B
  const rankLabels = ['PRIMARY', 'SECONDARY', 'TERTIARY']
  const rankColors = ['hsl(var(--primary))', 'hsl(var(--time))', 'hsl(var(--muted-foreground))']

  return (
    <div className="space-y-1.5 border-t border-border/60 pt-3 first:border-t-0 first:pt-0">
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-center gap-2">
          <span
            className="rounded px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-[0.2em]"
            style={{ background: `${rankColors[rank]}1a`, color: rankColors[rank] }}
          >
            {rankLabels[rank] ?? `#${rank + 1}`}
          </span>
          <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-foreground">
            {CAUSE_LABELS[cause_type] ?? cause_type}
          </span>
        </div>
        <div className="flex items-center gap-2 text-[10px]">
          {distance_m != null && (
            <span className="font-mono-data text-muted-foreground/60">{distance_m}m</span>
          )}
          <span className="font-mono-data font-semibold" style={{ color: winColor }}>
            {winner} +{mag.toFixed(1)} kph
          </span>
        </div>
      </div>

      {/* Bar */}
      <div className="relative h-2 overflow-hidden rounded-full" style={{ background: 'hsl(0,0%,10%)' }}>
        <div
          className="absolute inset-y-0 left-0 rounded-full transition-all duration-700"
          style={{
            width: `${barPct}%`,
            background: `linear-gradient(90deg, ${winColor}55, ${winColor})`,
            boxShadow: `0 0 8px ${winColor}55`,
          }}
        />
      </div>

      {/* Explanation text */}
      {explanation && (
        <div className="text-[11px] leading-5 text-muted-foreground">{explanation}</div>
      )}
    </div>
  )
}

// ── Style panel ───────────────────────────────────────────────────────────

function StylePanel({ style, driverA, driverB }) {
  const a = style?.driver_a_style ?? style?.driver_a
  const b = style?.driver_b_style ?? style?.driver_b
  const prediction = style?.style_prediction
  if (!a && !b && !prediction) return null

  return (
    <div
      className="space-y-3 rounded-md border px-3 py-3"
      style={{ borderColor: 'hsl(var(--primary) / 0.15)', background: 'hsl(var(--primary) / 0.03)' }}
    >
      <div className="text-[9px] font-medium uppercase tracking-[0.22em]"
        style={{ color: 'hsl(var(--primary) / 0.6)' }}>
        Driving Style
      </div>

      {(a || b) && (
        <div className="grid gap-3 sm:grid-cols-2">
          {[{ code: driverA, profile: a, color: COLOR_A }, { code: driverB, profile: b, color: COLOR_B }].map(({ code, profile, color }) => (
            profile ? (
              <div key={code} className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <span
                    className="rounded px-1.5 py-0.5 text-[10px] font-bold uppercase"
                    style={{ background: `${color}1a`, color }}
                  >
                    {code}
                  </span>
                  <span className="text-[10px] capitalize text-muted-foreground">
                    {profile.corner_approach?.replace('_', '-')} · {profile.steering_style}
                  </span>
                </div>
                {profile.key_traits?.slice(0, 2).map((trait, i) => (
                  <div key={i} className="flex items-start gap-1.5 text-[11px] text-muted-foreground">
                    <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full" style={{ background: color }} />
                    {trait}
                  </div>
                ))}
              </div>
            ) : null
          ))}
        </div>
      )}

      {prediction && (
        <div
          className="rounded border-l-2 py-1.5 pl-3 text-[11px] leading-5 text-muted-foreground"
          style={{ borderColor: 'hsl(var(--primary) / 0.3)' }}
        >
          {prediction}
        </div>
      )}
    </div>
  )
}

// ── Main widget ───────────────────────────────────────────────────────────

export default function QualifyingBattleWidget({ widget }) {
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

  const topCauses = widget.cause_explanations ?? []
  const maxMag = Math.max(...topCauses.map((c) => Math.abs(c.delta_speed_kph ?? 0)), 1)

  const tracePoints = widget.focus_window_trace?.length ? widget.focus_window_trace : widget.speed_trace
  const decisiveDistance = widget.focus_window_trace?.length
    ? widget.focus_window_trace[Math.floor(widget.focus_window_trace.length / 2)]?.distance_m
    : widget.speed_trace?.length
      ? widget.speed_trace[Math.floor(widget.speed_trace.length / 2)]?.distance_m
      : null

  return (
    <div className="widget-enter max-w-3xl space-y-0 overflow-hidden rounded-lg border border-border/90 bg-card">
      {/* ── Top accent bar ─────────────────────────────────────────── */}
      <div
        className="h-[2px] w-full"
        style={{
          background: `linear-gradient(90deg, ${COLOR_A}, hsl(var(--primary) / 0.3) 40%, hsl(var(--speed) / 0.3) 60%, ${COLOR_B})`,
        }}
      />

      <div className="p-4 space-y-4">
        {/* ── Event header ──────────────────────────────────────────── */}
        <div className="flex items-center justify-between gap-2">
          <div className="text-[9px] font-medium uppercase tracking-[0.22em]"
            style={{ color: 'hsl(var(--primary) / 0.65)' }}>
            Qualifying Battle
          </div>
          <div className="text-[10px] text-muted-foreground/60">
            {widget.event}{widget.session ? ` · ${widget.session}` : ''}
          </div>
        </div>

        {/* ── Driver face-off ────────────────────────────────────────── */}
        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3">
          {/* Driver A */}
          <div className="space-y-1">
            <div
              className="inline-block rounded px-2 py-0.5 text-sm font-bold uppercase tracking-wide"
              style={{ background: `${COLOR_A}1a`, border: `1px solid ${COLOR_A}44`, color: COLOR_A }}
            >
              {driverA}
            </div>
            <div
              className="font-mono-data text-2xl font-bold leading-none tracking-tight"
              style={{ color: fasterIsA ? COLOR_A : 'hsl(var(--foreground) / 0.5)' }}
            >
              {lapA ? formatTime(lapA) : '—'}
            </div>
            {fasterIsA && (
              <div
                className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-[0.15em]"
                style={{ background: `${COLOR_A}18`, color: COLOR_A }}
              >
                ✓ FASTER
              </div>
            )}
          </div>

          {/* Gap / VS */}
          <div className="flex flex-col items-center gap-1 px-2">
            <div className="text-[9px] uppercase tracking-[0.2em] text-muted-foreground/50">Gap</div>
            <div
              className="font-mono-data text-xl font-bold"
              style={{ color: 'hsl(var(--time))' }}
            >
              {formatGap(widget.overall_gap_s) ?? '—'}
            </div>
            <div className="text-[9px] text-muted-foreground/40">◄ ►</div>
          </div>

          {/* Driver B */}
          <div className="space-y-1 text-right">
            <div
              className="inline-block rounded px-2 py-0.5 text-sm font-bold uppercase tracking-wide"
              style={{ background: `${COLOR_B}1a`, border: `1px solid ${COLOR_B}44`, color: COLOR_B }}
            >
              {driverB}
            </div>
            <div
              className="font-mono-data text-2xl font-bold leading-none tracking-tight"
              style={{ color: !fasterIsA ? COLOR_B : 'hsl(var(--foreground) / 0.5)' }}
            >
              {lapB ? formatTime(lapB) : '—'}
            </div>
            {!fasterIsA && (
              <div
                className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-[0.15em]"
                style={{ background: `${COLOR_B}18`, color: COLOR_B }}
              >
                ✓ FASTER
              </div>
            )}
          </div>
        </div>

        {/* Teammate badge */}
        {widget.is_teammate_comparison && (
          <div
            className="rounded-md border px-3 py-2 text-[11px] text-muted-foreground"
            style={{ borderColor: 'hsl(var(--border) / 0.6)', background: 'hsl(var(--secondary) / 0.4)' }}
          >
            {widget.teammate_context ?? 'Same team — differences reflect driving style and setup, not car performance.'}
          </div>
        )}

        {/* ── Sector breakdown ──────────────────────────────────────── */}
        {(s1 || s2 || s3) && (
          <div className="space-y-0 rounded-md border border-border/70 overflow-hidden">
            <div className="border-b border-border/60 px-3 py-2 bg-secondary/20">
              <div className="text-[9px] font-medium uppercase tracking-[0.22em] text-muted-foreground/70">
                Sector Breakdown
              </div>
            </div>
            <div className="px-3 py-3 space-y-3">
              {[
                { key: 'sector1', label: 'S1', data: s1 },
                { key: 'sector2', label: 'S2', data: s2 },
                { key: 'sector3', label: 'S3', data: s3 },
              ].filter(({ data }) => data).map(({ key, label, data }) => (
                <SectorBar
                  key={key}
                  sectorKey={key}
                  label={label}
                  sectorData={data}
                  maxAbsGap={maxAbsGap}
                  driverA={driverA}
                  driverB={driverB}
                  fasterDriver={widget.faster_driver}
                />
              ))}
              {/* Speed trap */}
              {widget.sector_comparison?.speed_trap_a != null && (
                <div className="grid grid-cols-[2rem_minmax(0,1fr)_5.5rem] items-center gap-3 border-t border-border/60 pt-3">
                  <div className="text-[10px] font-semibold uppercase tracking-[0.15em] text-muted-foreground">ST</div>
                  <div className="flex items-center gap-2 text-[11px] font-mono-data">
                    <span style={{ color: fasterIsA ? COLOR_A : 'hsl(var(--muted-foreground))' }}>
                      {widget.sector_comparison.speed_trap_a?.toFixed(1)} kph
                    </span>
                    <span className="text-muted-foreground/40">/</span>
                    <span style={{ color: !fasterIsA ? COLOR_B : 'hsl(var(--muted-foreground))' }}>
                      {widget.sector_comparison.speed_trap_b?.toFixed(1)} kph
                    </span>
                  </div>
                  <div className="text-right text-[10px] font-mono-data">
                    {typeof widget.sector_comparison.speed_trap_delta === 'number' && (
                      <span style={{ color: widget.sector_comparison.speed_trap_delta < 0 ? COLOR_A : COLOR_B }}>
                        {widget.sector_comparison.speed_trap_delta < 0 ? driverA : driverB}{' '}
                        +{Math.abs(widget.sector_comparison.speed_trap_delta).toFixed(1)} kph
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Speed trace ───────────────────────────────────────────── */}
        {tracePoints?.length ? (
          <SpeedTraceChart
            points={tracePoints}
            driverA={driverA}
            driverB={driverB}
            decisiveDistance={decisiveDistance}
            decisiveCorner={widget.decisive_corner}
          />
        ) : null}

        {/* ── Key mechanisms ────────────────────────────────────────── */}
        {topCauses.length > 0 && (
          <div className="rounded-md border border-border/70 overflow-hidden">
            <div className="border-b border-border/60 px-3 py-2 bg-secondary/20">
              <div className="text-[9px] font-medium uppercase tracking-[0.22em] text-muted-foreground/70">
                Key Mechanisms
              </div>
            </div>
            <div className="px-3 py-3 space-y-3">
              {topCauses.map((cause, i) => (
                <MechanismRow
                  key={cause.cause_type}
                  cause={cause}
                  rank={i}
                  maxMag={maxMag}
                  driverA={driverA}
                  driverB={driverB}
                />
              ))}
            </div>
          </div>
        )}

        {/* Fallback: single cause explanation (old data without cause_explanations) */}
        {topCauses.length === 0 && widget.cause_explanation && (
          <div className="rounded-md border border-border/80 bg-secondary/20 px-3 py-2.5">
            <div className="text-[9px] font-medium uppercase tracking-[0.2em] text-muted-foreground/80">Mechanism</div>
            <div className="mt-1 text-sm leading-6 text-foreground">{widget.cause_explanation}</div>
          </div>
        )}

        {/* Energy signal */}
        {widget.energy_relevant && widget.energy_reason && (
          <div
            className="rounded-md border px-3 py-2.5"
            style={{ borderColor: `${COLOR_B}33`, background: `${COLOR_B}0a` }}
          >
            <div className="text-[9px] font-medium uppercase tracking-[0.2em]"
              style={{ color: `${COLOR_B}bb` }}>
              ERS / Energy Signal
            </div>
            <div className="mt-1 text-[11px] leading-5 text-muted-foreground">{widget.energy_reason}</div>
          </div>
        )}

        {/* ── Style comparison ──────────────────────────────────────── */}
        {widget.style_comparison && (
          <StylePanel
            style={widget.style_comparison}
            driverA={driverA}
            driverB={driverB}
          />
        )}
      </div>
    </div>
  )
}
