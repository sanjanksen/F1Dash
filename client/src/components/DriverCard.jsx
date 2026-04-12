// client/src/components/DriverCard.jsx
import { useEffect, useRef } from 'react'

function useCountUp(value, duration = 750) {
  const ref = useRef(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const to = Number(value) || 0
    const start = performance.now()
    const step = (now) => {
      const t = Math.min((now - start) / duration, 1)
      const eased = 1 - Math.pow(1 - t, 3)
      el.textContent = Math.round(to * eased)
      if (t < 1) requestAnimationFrame(step)
    }
    requestAnimationFrame(step)
  }, [value, duration])
  return ref
}

const POS_COLOR = { 1: 'var(--gold)', 2: 'var(--silver)', 3: 'var(--bronze)' }

export default function DriverCard({ stats }) {
  if (!stats) return null
  const pos = stats.championship_position
  const posColor = POS_COLOR[pos] ?? 'var(--text-muted)'

  const winsRef    = useCountUp(stats.wins)
  const podiumsRef = useCountUp(stats.podiums)
  const fastestRef = useCountUp(stats.fastest_laps)

  return (
    <div className="driver-card card animate-in">
      <div className="driver-watermark" aria-hidden="true">{pos}</div>

      <div className="driver-header">
        <div className="driver-info">
          <span className="driver-code">{stats.code}</span>
          <h2 className="driver-name">{stats.driver}</h2>
          <span className="driver-team">{stats.team}</span>
        </div>
        <div className="driver-pos-block">
          <span className="pos-letter">P</span>
          <span className="pos-number" style={{ color: posColor }}>{pos}</span>
          <span className="pos-pts">{stats.points} pts</span>
        </div>
      </div>

      <div className="stats-grid">
        <div className="stat-cell">
          <span className="stat-num" ref={winsRef} style={{ color: 'var(--accent)' }}>0</span>
          <span className="stat-label">Wins</span>
        </div>
        <div className="stat-cell">
          <span className="stat-num" ref={podiumsRef}>0</span>
          <span className="stat-label">Podiums</span>
        </div>
        <div className="stat-cell">
          <span className="stat-num" ref={fastestRef}>0</span>
          <span className="stat-label">Fastest Laps</span>
        </div>
        <div className="stat-cell">
          <span className="stat-num">{stats.nationality?.slice(0, 3).toUpperCase() ?? '—'}</span>
          <span className="stat-label">Origin</span>
        </div>
      </div>

      {stats.recent_races?.length > 0 && (
        <div className="recent-races">
          <p className="section-label" style={{ marginBottom: '0.75rem' }}>Recent Races</p>
          {stats.recent_races.map((race, i) => {
            const rColor = POS_COLOR[race.position] ?? 'var(--text-primary)'
            return (
              <div
                key={i}
                className="race-row animate-in"
                style={{ animationDelay: `${0.08 + i * 0.05}s` }}
              >
                <span className="race-name">{race.race}</span>
                <div className="race-meta">
                  {race.fastest_lap && <span className="fl-tag">FL</span>}
                  <span className="race-pos" style={{ color: rColor }}>P{race.position}</span>
                  <span className="race-pts">{race.points}p</span>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
