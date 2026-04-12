import { useEffect, useRef } from 'react'

import { Badge } from './ui/badge.jsx'
import { Card, CardContent } from './ui/card.jsx'

function useCountUp(value, duration = 700) {
  const ref = useRef(null)

  useEffect(() => {
    const element = ref.current
    if (!element) return

    const target = Number(value) || 0
    const start = performance.now()
    let frameId

    const step = (now) => {
      const progress = Math.min((now - start) / duration, 1)
      const eased = 1 - (1 - progress) ** 3
      element.textContent = String(Math.round(target * eased))
      if (progress < 1) frameId = requestAnimationFrame(step)
    }

    frameId = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frameId)
  }, [value, duration])

  return ref
}

const podiumTone = {
  1: 'text-foreground',
  2: 'text-zinc-300',
  3: 'text-zinc-400',
}

export default function DriverCard({ stats }) {
  if (!stats) return null

  const winsRef = useCountUp(stats.wins)
  const podiumsRef = useCountUp(stats.podiums)
  const fastestRef = useCountUp(stats.fastest_laps)
  const positionTone = podiumTone[stats.championship_position] || 'text-muted-foreground'

  return (
    <Card className="overflow-hidden">
      <CardContent className="p-0">
        <div className="grid gap-0 lg:grid-cols-[minmax(0,1.5fr)_20rem]">
          <div className="border-b border-border p-6 lg:border-b-0 lg:border-r">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <Badge variant="muted" className="mb-3">
                  {stats.code}
                </Badge>
                <h2 className="text-3xl font-semibold tracking-[-0.04em] text-foreground">
                  {stats.driver}
                </h2>
                <p className="mt-2 text-sm text-muted-foreground">{stats.team}</p>
              </div>
              <div className="text-right">
                <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                  Championship
                </div>
                <div className={`mt-2 text-5xl font-semibold tracking-[-0.05em] ${positionTone}`}>
                  P{stats.championship_position}
                </div>
                <div className="mt-1 text-sm text-muted-foreground">{stats.points} pts</div>
              </div>
            </div>

            <div className="mt-8 grid gap-3 md:grid-cols-4">
              <div className="rounded-lg border border-border bg-background px-4 py-4">
                <div ref={winsRef} className="text-3xl font-semibold tracking-[-0.04em] text-primary">
                  0
                </div>
                <div className="mt-1 text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                  Wins
                </div>
              </div>
              <div className="rounded-lg border border-border bg-background px-4 py-4">
                <div ref={podiumsRef} className="text-3xl font-semibold tracking-[-0.04em] text-foreground">
                  0
                </div>
                <div className="mt-1 text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                  Podiums
                </div>
              </div>
              <div className="rounded-lg border border-border bg-background px-4 py-4">
                <div ref={fastestRef} className="text-3xl font-semibold tracking-[-0.04em] text-foreground">
                  0
                </div>
                <div className="mt-1 text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                  Fastest laps
                </div>
              </div>
              <div className="rounded-lg border border-border bg-background px-4 py-4">
                <div className="text-3xl font-semibold tracking-[-0.04em] text-foreground">
                  {stats.nationality?.slice(0, 3).toUpperCase() || '---'}
                </div>
                <div className="mt-1 text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                  Origin
                </div>
              </div>
            </div>
          </div>

          <div className="p-6">
            <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
              Recent races
            </div>
            <div className="mt-4 space-y-3">
              {stats.recent_races?.length > 0 ? (
                stats.recent_races.map((race) => (
                  <div
                    key={race.race}
                    className="flex items-center justify-between gap-3 border-b border-border pb-3 last:border-b-0 last:pb-0"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-foreground">{race.race}</div>
                      <div className="mt-1 text-xs text-muted-foreground">{race.points} points</div>
                    </div>
                    <div className="flex items-center gap-2 text-sm">
                      {race.fastest_lap ? <Badge variant="accent">FL</Badge> : null}
                      <span className="font-medium text-foreground">
                        {race.position != null ? `P${race.position}` : 'DNF'}
                      </span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="text-sm text-muted-foreground">No recent races available.</div>
              )}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
