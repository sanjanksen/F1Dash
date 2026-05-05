import { useEffect, useRef } from 'react'

import { Badge } from './ui/badge.jsx'

function useCountUp(value, duration = 500) {
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

const NATIONALITY_ISO3 = {
  British: 'GBR',
  Dutch: 'NLD',
  Spanish: 'ESP',
  Monegasque: 'MCO',
  Australian: 'AUS',
  Mexican: 'MEX',
  Finnish: 'FIN',
  French: 'FRA',
  German: 'DEU',
  Canadian: 'CAN',
  Thai: 'THA',
  Japanese: 'JPN',
  Chinese: 'CHN',
  Italian: 'ITA',
  Danish: 'DNK',
  American: 'USA',
  'New Zealander': 'NZL',
  Austrian: 'AUT',
  Argentinian: 'ARG',
  Brazilian: 'BRA',
  Belgian: 'BEL',
  Swiss: 'CHE',
  'South African': 'ZAF',
  Venezuelan: 'VEN',
  Colombian: 'COL',
  Czech: 'CZE',
  Hungarian: 'HUN',
  Polish: 'POL',
  Indonesian: 'IDN',
  Uruguayan: 'URY',
}

export default function DriverCard({ stats }) {
  if (!stats) return null

  const winsRef = useCountUp(stats.wins)
  const podiumsRef = useCountUp(stats.podiums)
  const fastestRef = useCountUp(stats.fastest_laps)
  const origin = (stats.nationality && NATIONALITY_ISO3[stats.nationality]) || stats.nationality?.slice(0, 3).toUpperCase() || '---'

  return (
    <div className="overflow-hidden rounded-2xl border border-border/80 bg-card">
      <div className="grid lg:grid-cols-[minmax(0,1.4fr)_20rem]">
        <div className="border-b border-border/70 p-5 lg:border-b-0 lg:border-r">
          <div className="flex flex-wrap items-start justify-between gap-5">
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-3xl font-semibold tracking-[-0.04em] text-foreground">{stats.driver}</h2>
                <Badge variant="muted">{stats.code}</Badge>
              </div>
              <p className="mt-2 text-sm text-muted-foreground">{stats.team}</p>
            </div>
            <div className="text-left sm:text-right">
              <div className="text-sm text-muted-foreground">Championship</div>
              <div className="mt-1 text-4xl font-semibold tracking-[-0.05em] text-foreground">
                P{stats.championship_position}
              </div>
              <div className="mt-1 text-sm text-muted-foreground">{stats.points} pts</div>
            </div>
          </div>

          <div className="mt-7 grid gap-px overflow-hidden rounded-xl border border-border/80 bg-border sm:grid-cols-4">
            {[
              ['Wins', winsRef, '0'],
              ['Podiums', podiumsRef, '0'],
              ['Fastest laps', fastestRef, '0'],
              ['Origin', null, origin],
            ].map(([label, ref, fallback]) => (
              <div key={label} className="bg-background/80 px-4 py-4">
                <div ref={ref || undefined} className="text-2xl font-semibold tracking-[-0.04em] text-foreground">
                  {fallback}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">{label}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="p-5">
          <div className="text-sm font-medium text-foreground">Recent races</div>
          <div className="mt-4 divide-y divide-border/70">
            {stats.recent_races?.length > 0 ? (
              stats.recent_races.map((race) => (
                <div key={race.race} className="flex items-center justify-between gap-3 py-3 first:pt-0 last:pb-0">
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
    </div>
  )
}
