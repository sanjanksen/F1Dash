const COLOR_A = 'hsl(var(--primary))'
const COLOR_B = 'hsl(var(--speed))'
const ZONE_LICO = 'hsl(var(--time) / 0.3)'
const ZONE_CLIP = 'hsl(var(--primary) / 0.22)'
const BORDER_LICO = 'hsl(var(--time))'
const BORDER_CLIP = 'hsl(var(--primary))'

const W = 640, H = 140
const PAD = { top: 10, right: 12, bottom: 28, left: 44 }
const IW = W - PAD.left - PAD.right
const IH = H - PAD.top - PAD.bottom

function SpeedPanel({ traceA, traceB, licoA, clipA, driverA, driverB }) {
  if (!traceA?.length) return null

  const all = [...traceA, ...(traceB ?? [])]
  const distances = all.map((p) => p.distance_m)
  const speeds    = all.map((p) => p.speed_kph)
  const minD = Math.min(...distances), maxD = Math.max(...distances)
  const minS = Math.min(...speeds) - 10, maxS = Math.max(...speeds) + 10
  const dSpan = maxD - minD || 1
  const sSpan = maxS - minS || 1

  const toX = (d) => PAD.left + ((d - minD) / dSpan) * IW
  const toY = (s) => PAD.top + IH - ((s - minS) / sSpan) * IH
  const poly = (pts) => pts.map((p) => `${toX(p.distance_m)},${toY(p.speed_kph)}`).join(' ')

  const step = sSpan > 150 ? 50 : sSpan > 80 ? 25 : 20
  const ticks = []
  let t = Math.ceil(minS / step) * step
  while (t <= maxS) { ticks.push(t); t += step }

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="block overflow-visible">
      {/* Harvest zones (LiCo) */}
      {(licoA ?? []).map((ev, i) => {
        const cx = toX(ev.distance_m ?? 0)
        return <rect key={i} x={cx - 15} y={PAD.top} width={30} height={IH}
          fill={ZONE_LICO} stroke={BORDER_LICO} strokeWidth={0.5} strokeOpacity={0.4} />
      })}
      {/* Clipping zones */}
      {(clipA ?? []).map((c, i) => {
        const x1 = toX(c.start_distance_m ?? 0)
        const x2 = toX(c.end_distance_m ?? 0)
        return <rect key={i} x={x1} y={PAD.top} width={Math.max(x2 - x1, 4)} height={IH}
          fill={ZONE_CLIP} stroke={BORDER_CLIP} strokeWidth={0.5} strokeOpacity={0.4} />
      })}
      {/* Grid */}
      {ticks.map((s) => (
        <g key={s}>
          <line x1={PAD.left} x2={W - PAD.right} y1={toY(s)} y2={toY(s)}
            stroke="hsl(var(--border))" strokeWidth={0.5} />
          <text x={PAD.left - 4} y={toY(s) + 3.5} textAnchor="end" fontSize={9}
            fill="hsl(var(--muted-foreground))">{s}</text>
        </g>
      ))}
      {/* Traces */}
      <polyline points={poly(traceA)} fill="none" stroke={COLOR_A} strokeWidth={1.5} strokeOpacity={0.9} />
      {traceB?.length > 0 && (
        <polyline points={poly(traceB)} fill="none" stroke={COLOR_B} strokeWidth={1.5} strokeOpacity={0.85} />
      )}
      {/* Driver labels */}
      {driverA && <text x={W - PAD.right} y={PAD.top + 10} textAnchor="end" fontSize={9} fill={COLOR_A} fontWeight="600">{driverA}</text>}
      {driverB && <text x={W - PAD.right} y={PAD.top + 22} textAnchor="end" fontSize={9} fill={COLOR_B} fontWeight="600">{driverB}</text>}
      {/* X label */}
      <text x={PAD.left + IW / 2} y={H - 4} textAnchor="middle" fontSize={9} fill="hsl(var(--muted-foreground))">Distance (m)</text>
      {/* Axes */}
      <line x1={PAD.left} x2={PAD.left} y1={PAD.top} y2={H - PAD.bottom} stroke="hsl(var(--border))" strokeWidth={1} />
      <line x1={PAD.left} x2={W - PAD.right} y1={H - PAD.bottom} y2={H - PAD.bottom} stroke="hsl(var(--border))" strokeWidth={1} />
    </svg>
  )
}

function MetricCell({ label, valueA, valueB, colorA = COLOR_A, colorB = COLOR_B, lowerIsBetter = true }) {
  const aNum = typeof valueA === 'number' ? valueA : null
  const bNum = typeof valueB === 'number' ? valueB : null
  const aWins = aNum !== null && bNum !== null && (lowerIsBetter ? aNum < bNum : aNum > bNum)
  const bWins = aNum !== null && bNum !== null && (lowerIsBetter ? bNum < aNum : bNum > aNum)
  return (
    <div className="bg-background py-3 sm:px-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 flex gap-3 text-sm font-mono-data font-medium">
        <span style={{ color: aWins ? colorA : 'hsl(var(--foreground))' }}>{valueA ?? '—'}</span>
        {valueB !== undefined && (
          <span style={{ color: bWins ? colorB : 'hsl(var(--muted-foreground))' }}>{valueB ?? '—'}</span>
        )}
      </div>
    </div>
  )
}

export default function EnergyManagementWidget({ widget }) {
  const traceA   = widget.speed_trace_a ?? []
  const traceB   = widget.speed_trace_b
  const mA       = widget.energy_metrics_a ?? {}
  const mB       = widget.energy_metrics_b
  const driverA  = widget.driver_a
  const driverB  = widget.driver_b
  const licoA    = (widget.drivers?.[0]?.likely_lift_and_coast_events ?? []).slice(0, 10)
  const clipA    = (widget.drivers?.[0]?.possible_clipping_windows   ?? []).slice(0, 8)
  const straights = widget.straight_breakdown ?? []

  if (!traceA.length) return null

  return (
    <div className="widget-enter max-w-3xl overflow-hidden border-y border-border/80 py-1">
      {/* Header */}
      <div className="flex items-center justify-between py-3">
        <h4 className="text-sm font-medium text-foreground">{widget.title}</h4>
        <div className="flex gap-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <span className="inline-block h-2.5 w-4 rounded-sm opacity-60"
              style={{ background: ZONE_LICO, border: `1px solid ${BORDER_LICO}` }} />
            Lift &amp; coast
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2.5 w-4 rounded-sm opacity-60"
              style={{ background: ZONE_CLIP, border: `1px solid ${BORDER_CLIP}` }} />
            Clipping
          </span>
        </div>
      </div>
      <p className="mb-2 text-xs text-muted-foreground">
        Speed trace with inferred ERS zones. Confidence: <span className="text-foreground">{widget.confidence ?? '—'}</span>.
        ERS state not directly measured — zones inferred from throttle/speed patterns.
      </p>

      {/* Speed trace */}
      <div className="overflow-x-auto">
        <SpeedPanel
          traceA={traceA} traceB={traceB}
          licoA={licoA} clipA={clipA}
          driverA={driverA} driverB={driverB}
        />
      </div>

      {/* Metrics comparison */}
      <div className="mt-1 grid gap-px bg-border/70 border-t border-border/70 sm:grid-cols-3">
        {driverA && (
          <div className="bg-background py-2 text-xs font-medium" style={{ color: COLOR_A }}>
            {driverA}{driverB ? <span style={{ color: COLOR_B }}> / {driverB}</span> : ''}
          </div>
        )}
      </div>
      <div className="grid gap-px bg-border/70 sm:grid-cols-3">
        <MetricCell
          label="Clips" valueA={mA.clip_count} valueB={mB?.clip_count} lowerIsBetter />
        <MetricCell
          label="Est. time lost (s)"
          valueA={mA.estimated_time_lost_to_clipping_s?.toFixed(3)}
          valueB={mB?.estimated_time_lost_to_clipping_s?.toFixed(3)}
          lowerIsBetter />
        <MetricCell
          label="Speed drop (kph)"
          valueA={mA.total_late_speed_drop_kph?.toFixed(1)}
          valueB={mB?.total_late_speed_drop_kph?.toFixed(1)}
          lowerIsBetter />
        <MetricCell
          label="Lifts (harvest)"
          valueA={mA.lico_count} valueB={mB?.lico_count}
          lowerIsBetter={false} />
        <MetricCell
          label="Harvest dist (m)"
          valueA={mA.total_harvest_distance_m?.toFixed(0)}
          valueB={mB?.total_harvest_distance_m?.toFixed(0)}
          lowerIsBetter={false} />
        <MetricCell
          label="Clip dist (m)"
          valueA={mA.total_clip_distance_m?.toFixed(0)}
          valueB={mB?.total_clip_distance_m?.toFixed(0)}
          lowerIsBetter />
      </div>

      {/* Per-straight breakdown */}
      {straights.length > 0 && (
        <div className="mt-1 border-t border-border/70">
          <div className="py-2 text-xs font-medium text-foreground">Straight-by-straight</div>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="border-b border-border/70 text-muted-foreground">
                  <th className="py-1.5 pr-3 text-left">At (m)</th>
                  <th className="py-1.5 pr-3 text-left">Len</th>
                  <th className="py-1.5 pr-3 text-right">DRS</th>
                  <th className="py-1.5 pr-3 text-right" style={{ color: COLOR_A }}>{driverA} peak</th>
                  <th className="py-1.5 pr-3 text-right" style={{ color: COLOR_A }}>Clip</th>
                  {driverB && <>
                    <th className="py-1.5 pr-3 text-right" style={{ color: COLOR_B }}>{driverB} peak</th>
                    <th className="py-1.5 text-right" style={{ color: COLOR_B }}>Clip</th>
                  </>}
                </tr>
              </thead>
              <tbody>
                {straights.map((s, i) => (
                  <tr key={i} className="border-b border-border/50 last:border-0">
                    <td className="py-1.5 pr-3 font-mono-data text-muted-foreground">{s.start_m}</td>
                    <td className="py-1.5 pr-3 font-mono-data text-muted-foreground">{s.length_m}m</td>
                    <td className="py-1.5 pr-3 text-right text-muted-foreground">{s.drs ? 'Yes' : '—'}</td>
                    <td className="py-1.5 pr-3 text-right font-mono-data text-foreground">
                      {s.driver_a?.peak_kph ?? '—'}
                    </td>
                    <td className="py-1.5 pr-3 text-right" style={{ color: s.driver_a?.clipped ? 'hsl(var(--primary))' : 'hsl(var(--muted-foreground))' }}>
                      {s.driver_a?.clipped ? '●' : '○'}
                    </td>
                    {driverB && <>
                      <td className="py-1.5 pr-3 text-right font-mono-data text-foreground">
                        {s.driver_b?.peak_kph ?? '—'}
                      </td>
                      <td className="py-1.5 text-right" style={{ color: s.driver_b?.clipped ? 'hsl(var(--primary))' : 'hsl(var(--muted-foreground))' }}>
                        {s.driver_b?.clipped ? '●' : '○'}
                      </td>
                    </>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Inference summary */}
      {widget.inference_summary?.length > 0 && (
        <div className="border-t border-border/60 py-3">
          {widget.inference_summary.map((line, i) => (
            <p key={i} className="text-sm leading-6 text-muted-foreground">{line}</p>
          ))}
        </div>
      )}
    </div>
  )
}
