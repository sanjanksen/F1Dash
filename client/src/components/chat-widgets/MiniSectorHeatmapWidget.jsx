import React from 'react'

const COLOR_A = 'hsl(220 80% 55%)'
const COLOR_B = 'hsl(28 90% 55%)'
const COLOR_TIE = 'hsl(0 0% 60%)'

const CHART_W = 720
const CHART_H = 140
const PADDING = 24

function segmentColor(winner) {
  if (winner === 'A') return COLOR_A
  if (winner === 'B') return COLOR_B
  return COLOR_TIE
}

function CumulativeDeltaChart({ data, totalDelta }) {
  if (!data || data.length < 2) return null
  const maxDist = data[data.length - 1][0] || 1
  const ys = data.map(([, y]) => y)
  const minY = Math.min(...ys, 0)
  const maxY = Math.max(...ys, 0)
  const yRange = Math.max(maxY - minY, 0.01)

  const x = (m) => PADDING + (m / maxDist) * (CHART_W - PADDING * 2)
  const y = (s) => PADDING + ((maxY - s) / yRange) * (CHART_H - PADDING * 2)

  const path = data.map(([m, s], i) => `${i === 0 ? 'M' : 'L'} ${x(m).toFixed(1)} ${y(s).toFixed(1)}`).join(' ')

  return (
    <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`} style={{ width: '100%', height: 140 }}>
      {/* zero line */}
      <line x1={PADDING} x2={CHART_W - PADDING} y1={y(0)} y2={y(0)}
            stroke="hsl(0 0% 70%)" strokeDasharray="3 4" />
      <path d={path} fill="none" stroke="hsl(220 60% 45%)" strokeWidth={2} />
      <text x={CHART_W - PADDING} y={20} textAnchor="end" fontSize={11} fill="hsl(0 0% 30%)">
        Cumulative Δ (s)
      </text>
      {totalDelta != null && (
        <text x={CHART_W - PADDING} y={CHART_H - 8} textAnchor="end" fontSize={11} fill="hsl(0 0% 30%)">
          end Δ: {totalDelta.toFixed(3)}s
        </text>
      )}
    </svg>
  )
}

function MiniSectorBar({ segments, driverA, driverB }) {
  if (!segments || segments.length === 0) return null
  return (
    <div style={{ display: 'flex', width: '100%', height: 18, marginTop: 8, borderRadius: 4, overflow: 'hidden' }}>
      {segments.map((seg) => (
        <div
          key={seg.index}
          title={`Seg ${seg.index + 1}: ${seg.start_m.toFixed(0)}-${seg.end_m.toFixed(0)} m, Δ ${seg.delta_s.toFixed(3)}s (${seg.winner === 'A' ? driverA : seg.winner === 'B' ? driverB : 'tie'})`}
          style={{
            flex: 1,
            background: segmentColor(seg.winner),
            borderRight: '1px solid hsl(0 0% 100% / 0.4)',
          }}
        />
      ))}
    </div>
  )
}

export default function MiniSectorHeatmapWidget({ widget }) {
  if (!widget) return null
  if (widget.available === false) {
    return (
      <div style={{ padding: 12, color: 'hsl(0 0% 40%)' }}>
        Mini-sector comparison unavailable
        {widget.reason ? ` (${widget.reason})` : ''}.
      </div>
    )
  }

  const {
    driver_a, driver_b, lap_number, segments,
    cumulative_delta, total_delta_s,
    segments_won_a, segments_won_b, segments_tied,
    drs_mix_warning, weather_state,
  } = widget

  return (
    <div style={{ padding: 12, border: '1px solid hsl(0 0% 90%)', borderRadius: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <strong>Mini-sectors — Lap {lap_number}</strong>
        <span style={{ fontSize: 12, color: 'hsl(0 0% 40%)' }}>
          {weather_state && weather_state !== 'unknown' ? `${weather_state} · ` : ''}
          {segments?.length || 0} segments
        </span>
      </div>

      <div style={{ display: 'flex', gap: 12, marginTop: 8, fontSize: 13 }}>
        <span><span style={{ color: COLOR_A }}>■</span> {driver_a} ({segments_won_a || 0})</span>
        <span><span style={{ color: COLOR_B }}>■</span> {driver_b} ({segments_won_b || 0})</span>
        {segments_tied > 0 && (
          <span><span style={{ color: COLOR_TIE }}>■</span> tied ({segments_tied})</span>
        )}
      </div>

      <MiniSectorBar segments={segments} driverA={driver_a} driverB={driver_b} />

      {drs_mix_warning && (
        <div style={{ marginTop: 8, padding: 6, background: 'hsl(45 90% 92%)',
                      borderRadius: 4, fontSize: 12, color: 'hsl(30 70% 30%)' }}>
          ⚠ DRS-mix detected: one driver had DRS open in at least one segment where the other didn't.
          Gap in those segments is contaminated by DRS state, not pure pace.
        </div>
      )}

      <CumulativeDeltaChart data={cumulative_delta} totalDelta={total_delta_s} />

      <div style={{ marginTop: 6, fontSize: 11, color: 'hsl(0 0% 50%)' }}>
        Negative Δ = {driver_a} faster · Positive Δ = {driver_b} faster
      </div>
    </div>
  )
}
