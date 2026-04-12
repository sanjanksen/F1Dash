// client/src/components/CircuitList.jsx
export default function CircuitList({ circuits }) {
  if (!circuits?.length) return null
  const today = new Date().toISOString().split('T')[0]
  const year = circuits[0]?.date?.slice(0, 4) ?? new Date().getFullYear()

  return (
    <div>
      <p className="section-label" style={{ marginBottom: '1rem' }}>
        {year} Season — {circuits.length} Rounds
      </p>
      <div className="circuit-grid">
        {circuits.map((c, i) => {
          const isPast = c.date < today
          return (
            <div
              key={c.round}
              className={`circuit-card card animate-in${isPast ? ' is-past' : ''}`}
              style={{ animationDelay: `${i * 0.035}s` }}
            >
              <span className="circuit-round-num">
                {String(c.round).padStart(2, '0')}
              </span>
              <p className="circuit-event">{c.event_name}</p>
              <p className="circuit-location">{c.circuit_name}</p>
              <div className="circuit-footer">
                <span className="circuit-country">{c.country}</span>
                <span className="circuit-date">
                  {new Date(c.date + 'T12:00:00').toLocaleDateString('en-GB', {
                    day: 'numeric',
                    month: 'short',
                  })}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
