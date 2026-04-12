// client/src/components/StatsView.jsx
import { useState, useEffect } from 'react'
import { fetchDriverStats, fetchCircuits } from '../api/f1api.js'
import DriverCard from './DriverCard.jsx'
import CircuitList from './CircuitList.jsx'

export default function StatsView() {
  const [mode, setMode] = useState('driver')
  const [query, setQuery] = useState('')
  const [driverStats, setDriverStats] = useState(null)
  const [circuits, setCircuits] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (mode === 'circuits' && circuits.length === 0) {
      setLoading(true)
      setError('')
      fetchCircuits()
        .then(setCircuits)
        .catch(e => setError(e.message))
        .finally(() => setLoading(false))
    }
  }, [mode, circuits.length])

  const handleSearch = async (e) => {
    e.preventDefault()
    if (!query.trim()) return
    setLoading(true)
    setError('')
    setDriverStats(null)
    try {
      setDriverStats(await fetchDriverStats(query.trim()))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="stats-view">
      <div className="mode-bar">
        <button
          className={`mode-pill${mode === 'driver' ? ' active' : ''}`}
          onClick={() => { setMode('driver'); setDriverStats(null); setError('') }}
        >
          Driver Stats
        </button>
        <button
          className={`mode-pill${mode === 'circuits' ? ' active' : ''}`}
          onClick={() => setMode('circuits')}
        >
          Season Calendar
        </button>
      </div>

      {mode === 'driver' && (
        <form className="search-form" onSubmit={handleSearch}>
          <div className="search-wrap">
            <svg className="search-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <circle cx="8.5" cy="8.5" r="5.5" stroke="currentColor" strokeWidth="1.5" />
              <path d="M13 13l3.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <input
              className="search-input"
              type="text"
              placeholder="Search driver — name, code, or nationality…"
              value={query}
              onChange={e => setQuery(e.target.value)}
              autoFocus
            />
          </div>
          <button className="search-btn" type="submit" disabled={loading}>
            {loading ? <span className="spinner" /> : 'Search'}
          </button>
        </form>
      )}

      {error && (
        <div className="error-banner animate-in">⚠ {error}</div>
      )}

      {loading && mode === 'circuits' && (
        <p className="loading-hint">Loading calendar…</p>
      )}

      {mode === 'driver' && driverStats && <DriverCard stats={driverStats} />}

      {mode === 'circuits' && !loading && circuits.length > 0 && (
        <CircuitList circuits={circuits} />
      )}
      {mode === 'circuits' && !loading && circuits.length === 0 && !error && (
        <p className="loading-hint">No circuits found.</p>
      )}

      {mode === 'driver' && !driverStats && !error && !loading && (
        <div className="search-hint animate-in">
          <p className="hint-primary">Search any driver</p>
          <p className="hint-secondary">Try "Verstappen", "NOR", or "norris"</p>
        </div>
      )}
    </div>
  )
}
