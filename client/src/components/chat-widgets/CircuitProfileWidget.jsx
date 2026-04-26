import { Badge } from '../ui/badge.jsx'

const CHARACTER_LABELS = {
  street_like_mixed: 'Street-Like Mixed',
  high_speed_street: 'High-Speed Street',
  medium_speed_technical: 'Technical',
  high_speed_power: 'Power Circuit',
  slow_technical: 'Slow-Technical',
  high_speed_flowing: 'High-Speed Flowing',
  mixed: 'Mixed',
}

const STYLE_LABELS = {
  late_braker: 'Late-braker',
  v_line: 'V-line',
  u_line: 'U-line',
  balanced: 'Balanced',
}

const ENERGY_LABELS = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  very_high: 'Very High',
}

const DOWNFORCE_LABELS = {
  low: 'Low Downforce',
  medium_low: 'Medium-Low Downforce',
  medium: 'Medium Downforce',
  medium_high: 'Medium-High Downforce',
  high: 'High Downforce',
}

const VERDICT_LABELS = {
  v_line: 'V-line',
  u_line: 'U-line',
  late_braker: 'Late-braker',
  v_line_late_braker: 'V-line / Late-braker',
  u_line_late_braker: 'U-line / Late-braker',
  balanced: 'Balanced',
}

function SectorColumn({ label, sector }) {
  if (!sector) return null
  const styleLabel = STYLE_LABELS[sector.style_advantage] ?? sector.style_advantage ?? '—'
  const energyLabel = ENERGY_LABELS[sector.energy_demand] ?? sector.energy_demand ?? '—'

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border/60 p-3">
      <div className="text-xs font-semibold text-primary">{label}</div>
      <div className="flex flex-wrap gap-1.5">
        <Badge variant="muted" className="text-[11px]">{styleLabel}</Badge>
        <Badge variant="outline" className="text-[11px]">Energy: {energyLabel}</Badge>
      </div>
      <div className="text-xs leading-5 text-muted-foreground">{sector.description}</div>
    </div>
  )
}

function EnergyRow({ label, value }) {
  if (!value) return null
  const displayValue = ENERGY_LABELS[value] ?? value
  return (
    <div className="flex items-center justify-between border-b border-border/50 py-1.5 text-sm last:border-b-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium text-foreground">{displayValue}</span>
    </div>
  )
}

export default function CircuitProfileWidget({ widget }) {
  if (!widget) return null

  const {
    circuit_name,
    character,
    downforce_level,
    sector_1,
    sector_2,
    sector_3,
    energy_profile,
    style_verdict,
    tyre_challenge,
  } = widget

  const characterLabel = CHARACTER_LABELS[character] ?? character ?? '—'
  const downforceLabel = DOWNFORCE_LABELS[downforce_level] ?? null
  const verdictLabel = VERDICT_LABELS[style_verdict?.qualifier] ?? style_verdict?.qualifier ?? '—'

  return (
    <div className="rounded-xl border border-border bg-card text-card-foreground shadow-sm">
      {/* Header */}
      <div className="border-b border-border/70 px-5 py-4">
        <div className="text-base font-semibold text-foreground">{circuit_name ?? 'Circuit Profile'}</div>
        <div className="mt-1.5 flex flex-wrap gap-2">
          <Badge variant="default">{characterLabel}</Badge>
          {downforceLabel ? <Badge variant="outline">{downforceLabel}</Badge> : null}
        </div>
      </div>

      <div className="divide-y divide-border/60">
        {/* Sector breakdown */}
        {(sector_1 || sector_2 || sector_3) && (
          <div className="px-5 py-4">
            <div className="mb-3 text-sm font-medium text-foreground">Sector breakdown</div>
            <div className="grid gap-3 sm:grid-cols-3">
              <SectorColumn label="S1" sector={sector_1} />
              <SectorColumn label="S2" sector={sector_2} />
              <SectorColumn label="S3" sector={sector_3} />
            </div>
          </div>
        )}

        {/* Energy profile */}
        {energy_profile && (
          <div className="px-5 py-4">
            <div className="mb-3 text-sm font-medium text-foreground">Energy profile</div>
            <div className="rounded-lg border border-border/60 px-3 py-1">
              <EnergyRow label="Deployment demand" value={energy_profile.deployment_demand} />
              <EnergyRow label="Clipping risk" value={energy_profile.clipping_risk} />
              <EnergyRow label="Harvesting opportunity" value={energy_profile.harvesting_opportunity} />
            </div>
            {energy_profile.notes ? (
              <div className="mt-2 text-xs leading-5 text-muted-foreground">{energy_profile.notes}</div>
            ) : null}
          </div>
        )}

        {/* Style verdict */}
        {style_verdict && (
          <div className="px-5 py-4">
            <div className="mb-2 text-sm font-medium text-foreground">Style verdict</div>
            <div className="flex items-start gap-3">
              <Badge variant="muted" className="mt-0.5 shrink-0">{verdictLabel}</Badge>
              <p className="text-sm leading-6 text-muted-foreground">{style_verdict.explanation}</p>
            </div>
          </div>
        )}

        {/* Tyre challenge */}
        {tyre_challenge && (
          <div className="px-5 py-4">
            <div className="mb-1 text-sm font-medium text-foreground">Tyre challenge</div>
            <p className="text-sm leading-6 text-muted-foreground">{tyre_challenge}</p>
          </div>
        )}
      </div>
    </div>
  )
}
