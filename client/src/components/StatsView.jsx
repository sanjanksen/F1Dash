import { useEffect, useState } from 'react'
import { LoaderCircle, Search } from 'lucide-react'

import { fetchCircuits, fetchDriverStats } from '../api/f1api.js'
import CircuitList from './CircuitList.jsx'
import DriverCard from './DriverCard.jsx'
import { Button } from './ui/button.jsx'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card.jsx'
import { Input } from './ui/input.jsx'

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
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-6 py-6 lg:px-10">
      <div className="flex flex-col gap-4 border-b border-border pb-6">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
            Stats workspace
          </div>
          <h1 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-foreground">
            Search drivers or scan the calendar.
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-7 text-muted-foreground">
            Quick access to season standings, recent race form, and the full calendar in a cleaner
            lookup view.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => {
              setMode('driver')
              setDriverStats(null)
              setError('')
            }}
            className={
              mode === 'driver'
                ? 'rounded-md border border-primary/35 bg-primary/8 px-3 py-2 text-xs font-medium uppercase tracking-[0.12em] text-foreground'
                : 'rounded-md border border-border px-3 py-2 text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground'
            }
          >
            Driver stats
          </button>
          <button
            type="button"
            onClick={() => setMode('circuits')}
            className={
              mode === 'circuits'
                ? 'rounded-md border border-primary/35 bg-primary/8 px-3 py-2 text-xs font-medium uppercase tracking-[0.12em] text-foreground'
                : 'rounded-md border border-border px-3 py-2 text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground'
            }
          >
            Season calendar
          </button>
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
              className="pl-9"
              autoFocus
            />
          </div>
          <Button type="submit" disabled={loading} className="sm:min-w-28">
            {loading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : 'Search'}
          </Button>
        </form>
      )}

      {error && (
        <Card className="border-destructive/35 bg-destructive/8">
          <CardContent className="pt-5 text-sm text-foreground">{error}</CardContent>
        </Card>
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
        <Card>
          <CardContent className="pt-5 text-sm text-muted-foreground">No circuits found.</CardContent>
        </Card>
      )}

      {mode === 'driver' && !driverStats && !error && !loading && (
        <Card className="max-w-xl">
          <CardHeader>
            <CardTitle>Search any driver</CardTitle>
            <CardDescription>
              Try Verstappen, NOR, Norris, Leclerc, or Russell.
            </CardDescription>
          </CardHeader>
        </Card>
      )}
    </div>
  )
}
