import { Badge } from '../ui/badge.jsx'
import { formatTimeMagnitude, formatTimeDelta } from './formatTimeDelta.js'

function formatRowVal(val, fmt) {
  if (val == null) return '—'
  if (fmt === 'pct') return `${Number(val).toFixed(1)}%`
  if (fmt === 'count') return Number(val).toFixed(1)
  if (fmt === 'raw3') return Number(val).toFixed(3)
  return String(val)
}

const SECTION_META = {
  commitment: {
    label: 'Commitment',
    sub: 'how hard they asked the car',
    headerClass: 'bg-primary/8 border-primary/20',
    labelClass: 'text-primary',
  },
  technique: {
    label: 'Technique',
    sub: 'the flip side — how cleanly they executed',
    headerClass: 'bg-muted/40 border-border/50',
    labelClass: 'text-foreground',
  },
}

export function CornerAnalysisPanel({ grip, driverA, driverB }) {
  if (!grip) return null

  const committed = grip.more_committed_driver
  const cleaner   = grip.cleaner_driver

  const commitmentRows = (grip.data_rows || []).filter((r) => r.group === 'commitment')
  const techniqueRows  = (grip.data_rows || []).filter((r) => r.group === 'technique')

  const groups = [
    { key: 'commitment', rows: commitmentRows },
    { key: 'technique',  rows: techniqueRows  },
  ].filter((g) => g.rows.length > 0)

  const totalTimeGained = grip.total_time_gained_s
  const totalTimeStr = formatTimeMagnitude(totalTimeGained)
  const cornerRecords = Array.isArray(grip.corner_time_records) ? grip.corner_time_records : []

  return (
    <section className="py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h4 className="text-sm font-medium text-foreground">Corner analysis</h4>
        <div className="text-xs text-muted-foreground">From cornering load data</div>
      </div>

      {totalTimeStr ? (
        <div className="mt-2 text-sm text-foreground">
          Total time gained from grip differential:{' '}
          <span className="font-mono-data font-semibold">{totalTimeStr}</span>
        </div>
      ) : null}

      {grip.confidence_read ? (
        <div className="mt-2 text-sm leading-6 text-muted-foreground">{grip.confidence_read}</div>
      ) : null}

      {cornerRecords.length > 0 ? (
        <ul className="mt-3 space-y-1 text-xs">
          {cornerRecords.slice(0, 6).map((rec, i) => {
            const label = formatTimeDelta(rec.time_gained_s, { approximate: rec.time_gained_estimate })
            if (!label) return null
            return (
              <li key={i} className="flex items-baseline justify-between gap-3">
                <span className="text-muted-foreground">{rec.corner ?? rec.label ?? `Corner ${i + 1}`}</span>
                <span className="font-mono-data text-foreground">{label}</span>
              </li>
            )
          })}
        </ul>
      ) : null}

      {/* Driver summary badges */}
      <div className="mt-3 flex flex-wrap gap-4">
        {[driverA, driverB].map((code) => (
          <div key={code} className="flex items-center gap-2">
            <Badge variant={committed === code ? 'accent' : 'muted'}>{code}</Badge>
            {committed === code && cleaner !== code ? <span className="text-xs text-muted-foreground">more committed</span> : null}
            {cleaner === code && committed !== code ? <span className="text-xs text-muted-foreground">cleaner arc</span> : null}
            {cleaner === code && committed === code ? <span className="text-xs text-muted-foreground">committed + clean</span> : null}
            {cleaner !== code && committed !== code ? <span className="text-xs text-muted-foreground/60">—</span> : null}
          </div>
        ))}
      </div>

      {/* Two distinct boxed sections */}
      {groups.length > 0 && (
        <div className="mt-4 space-y-3">
          {groups.map(({ key, rows }) => {
            const meta = SECTION_META[key]
            return (
              <div key={key} className={`rounded-lg border overflow-hidden ${meta.headerClass}`}>
                <div className={`flex items-baseline gap-2 px-3 py-2 border-b ${meta.headerClass}`}>
                  <span className={`text-xs font-semibold ${meta.labelClass}`}>{meta.label}</span>
                  <span className="text-[10px] text-muted-foreground">{meta.sub}</span>
                </div>
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-border/30">
                      <th className="px-3 pb-1.5 pt-2 text-left text-[10px] font-normal text-muted-foreground w-[44%]">Metric</th>
                      <th className="pb-1.5 pt-2 pr-2 text-right text-[10px] font-normal text-muted-foreground">{driverA}</th>
                      <th className="pb-1.5 pt-2 pr-2 text-right text-[10px] font-normal text-muted-foreground">{driverB}</th>
                      <th className="pb-1.5 pt-2 pr-3 text-right text-[10px] font-normal text-muted-foreground">Edge</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, i) => (
                      <tr key={i} className="border-b border-border/15 last:border-0">
                        <td className="px-3 py-1.5 text-[11px] text-muted-foreground">{row.label}</td>
                        <td className={`py-1.5 pr-2 text-right font-mono text-xs tabular-nums ${row.edge === driverA ? 'font-semibold text-foreground' : 'text-muted-foreground/70'}`}>
                          {formatRowVal(row.a, row.format)}
                        </td>
                        <td className={`py-1.5 pr-2 text-right font-mono text-xs tabular-nums ${row.edge === driverB ? 'font-semibold text-foreground' : 'text-muted-foreground/70'}`}>
                          {formatRowVal(row.b, row.format)}
                        </td>
                        <td className="py-1.5 pr-3 text-right text-[10px] text-muted-foreground">
                          {row.edge ? `${row.edge} — ${row.edge_label}` : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

export default function CornerAnalysisWidget({ widget }) {
  return (
    <div className="rounded-xl border border-border/50 bg-card px-4 pb-2">
      <CornerAnalysisPanel
        grip={widget.grip}
        driverA={widget.driver_a}
        driverB={widget.driver_b}
      />
    </div>
  )
}
