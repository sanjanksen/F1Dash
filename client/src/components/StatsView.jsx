import { useEffect, useState } from 'react'
import { LoaderCircle, Search } from 'lucide-react'

import { fetchCircuits, fetchDriverStats } from '../api/f1api.js'
import CircuitList from './CircuitList.jsx'
import DriverCard from './DriverCard.jsx'
import { Button } from './ui/button.jsx'
import { Input } from './ui/input.jsx'
import { cn } from '@/lib/utils'

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
        .catch((nextError) => setError(nextError.message))
        .finally(() => setLoading(false))
    }
  }, [mode, circuits.length])

  const handleSearch = async (event) => {
    event.preventDefault()
    if (!query.trim()) return

    setLoading(true)
    setError('')
    setDriverStats(null)

    try {
      setDriverStats(await fetchDriverStats(query.trim()))
    } catch (nextError) {
      setError(nextError.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-5 py-8 sm:px-8">
      <div className="flex flex-col gap-5 border-b border-border/70 pb-5 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-[-0.03em] text-foreground">Stats</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            Search driver form or scan the season calendar.
          </p>
        </div>

        <div className="inline-flex w-fit items-center gap-1">
          {[
            ['driver', 'Driver stats'],
            ['circuits', 'Calendar'],
          ].map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => {
                setMode(value)
                setDriverStats(null)
                setError('')
              }}
              className={cn(
                'rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
                mode === value
                  ? 'bg-card text-foreground shadow-[0_1px_3px_rgba(51,38,23,0.08)]'
                  : 'text-muted-foreground hover:bg-card/60 hover:text-foreground',
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {mode === 'driver' && (
        <form onSubmit={handleSearch} className="flex flex-col gap-3 sm:flex-row">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              type="text"
              placeholder="Search driver by name or code, for example Verstappen or NOR"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="h-11 border-border/80 bg-card pl-9"
              autoFocus
            />
          </div>
          <Button type="submit" disabled={loading} className="h-11 sm:min-w-28">
            {loading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : 'Search'}
          </Button>
        </form>
      )}

      {error && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-foreground">
          {error}
        </div>
      )}

      {loading && mode === 'circuits' && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <LoaderCircle className="h-4 w-4 animate-spin" />
          <span>Loading calendar...</span>
        </div>
      )}

      {mode === 'driver' && driverStats && <DriverCard stats={driverStats} />}

      {mode === 'circuits' && !loading && circuits.length > 0 && <CircuitList circuits={circuits} />}

      {mode === 'circuits' && !loading && circuits.length === 0 && !error && (
        <div className="rounded-xl border border-border/80 bg-card px-4 py-3 text-sm text-muted-foreground">
          No circuits found.
        </div>
      )}

      {mode === 'driver' && !driverStats && !error && !loading && (
        <div className="max-w-xl rounded-xl border border-border/80 bg-card px-4 py-4 text-sm leading-6 text-muted-foreground">
          Try Verstappen, NOR, Norris, Leclerc, or Russell.
        </div>
      )}
    </div>
  )
}
