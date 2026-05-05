const MAP_W = 260
const MAP_H = 210
const PADDING = 18

const RANK_COLORS = [
  'hsl(var(--primary))',
  'hsl(var(--time))',
  'hsl(var(--accent))',
]
const RANK_LABELS = ['P', 'S', 'T']

function validPoints(points) {
  return (points ?? []).filter(
    (point) =>
      typeof point.x === 'number' &&
      typeof point.y === 'number' &&
      typeof point.distance_m === 'number',
  )
}

function getBounds(points) {
  const xs = points.map((point) => point.x)
  const ys = points.map((point) => point.y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const spanX = Math.max(maxX - minX, 1)
  const spanY = Math.max(maxY - minY, 1)
  const scale = Math.min((MAP_W - PADDING * 2) / spanX, (MAP_H - PADDING * 2) / spanY)
  const offsetX = (MAP_W - spanX * scale) / 2
  const offsetY = (MAP_H - spanY * scale) / 2
  return { minX, maxY, scale, offsetX, offsetY }
}

function projectPoint(point, bounds) {
  return {
    x: bounds.offsetX + (point.x - bounds.minX) * bounds.scale,
    y: bounds.offsetY + (bounds.maxY - point.y) * bounds.scale,
  }
}

function nearestByDistance(points, distance) {
  if (!points.length || typeof distance !== 'number') return null
  return points.reduce((best, point) =>
    Math.abs(point.distance_m - distance) < Math.abs(best.distance_m - distance) ? point : best
  )
}

function clampLabel(value, min, max) {
  return Math.min(Math.max(value, min), max)
}

function startFinishMark(points, bounds) {
  if (points.length < 2) return null
  const start = projectPoint(points[0], bounds)
  const next = projectPoint(points[1], bounds)
  const dx = next.x - start.x
  const dy = next.y - start.y
  const length = Math.hypot(dx, dy) || 1
  const normalX = -dy / length
  const normalY = dx / length
  const tick = 8
  const labelX = clampLabel(start.x + normalX * 14, 14, MAP_W - 14)
  const labelY = clampLabel(start.y + normalY * 14, 14, MAP_H - 14)

  return {
    x1: start.x - normalX * tick,
    y1: start.y - normalY * tick,
    x2: start.x + normalX * tick,
    y2: start.y + normalY * tick,
    labelX,
    labelY,
  }
}

export default function TrackMap({ points, causes = [], activeMechIndex, onMechHover }) {
  const mapPoints = validPoints(points)
  if (mapPoints.length < 3) return null

  const bounds = getBounds(mapPoints)
  const startFinish = startFinishMark(mapPoints, bounds)
  const path = mapPoints
    .map((point, index) => {
      const projected = projectPoint(point, bounds)
      return `${index === 0 ? 'M' : 'L'} ${projected.x.toFixed(1)} ${projected.y.toFixed(1)}`
    })
    .join(' ')

  const markers = causes.slice(0, 3).map((cause, index) => {
    const point = nearestByDistance(mapPoints, cause.distance_m)
    if (!point) return null
    const projected = projectPoint(point, bounds)
    return {
      index,
      point,
      distance: typeof cause.distance_m === 'number' ? cause.distance_m : point.distance_m,
      x: projected.x,
      y: projected.y,
      color: RANK_COLORS[index],
      label: RANK_LABELS[index],
    }
  }).filter(Boolean)

  return (
    <div className="overflow-hidden rounded-xl border border-border/80 bg-card">
      <div className="border-b border-border/80 px-3 py-2.5">
        <div className="text-sm font-medium text-foreground">Circuit position</div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          Same P/S/T markers, placed on the lap map.
        </div>
      </div>

      <div className="px-3 py-3">
        <svg viewBox={`0 0 ${MAP_W} ${MAP_H}`} className="h-52 w-full overflow-visible">
          <path
            d={path}
            fill="none"
            stroke="hsl(var(--border))"
            strokeWidth="11"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d={path}
            fill="none"
            stroke="hsl(var(--foreground))"
            strokeOpacity="0.72"
            strokeWidth="3.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {startFinish ? (
            <g>
              <line
                x1={startFinish.x1}
                y1={startFinish.y1}
                x2={startFinish.x2}
                y2={startFinish.y2}
                stroke="hsl(var(--foreground))"
                strokeWidth="2.5"
                strokeLinecap="round"
              />
              <line
                x1={startFinish.x1}
                y1={startFinish.y1}
                x2={startFinish.x2}
                y2={startFinish.y2}
                stroke="hsl(var(--card))"
                strokeWidth="1"
                strokeLinecap="round"
              />
              <text
                x={startFinish.labelX}
                y={startFinish.labelY + 3}
                textAnchor="middle"
                fill="hsl(var(--muted-foreground))"
                fontSize="9"
                fontFamily="monospace"
                fontWeight="700"
              >
                S/F
              </text>
            </g>
          ) : null}
          {markers.map((marker) => {
            const active = activeMechIndex === marker.index
            const labelX = clampLabel(marker.x + 15, 12, MAP_W - 12)
            const labelY = clampLabel(marker.y - 12, 12, MAP_H - 12)

            return (
              <g
                key={marker.label}
                onMouseEnter={() => onMechHover?.(marker.index)}
                onMouseLeave={() => onMechHover?.(null)}
                className="cursor-default"
              >
                <circle
                  cx={marker.x}
                  cy={marker.y}
                  r={active ? 8 : 6}
                  fill="hsl(var(--card))"
                  stroke={marker.color}
                  strokeWidth={active ? 4 : 3}
                />
                <line
                  x1={marker.x}
                  y1={marker.y}
                  x2={labelX}
                  y2={labelY}
                  stroke={marker.color}
                  strokeOpacity={active ? 0.85 : 0.42}
                  strokeWidth="1"
                />
                <rect
                  x={labelX - 8}
                  y={labelY - 8}
                  width="16"
                  height="16"
                  rx="3"
                  fill={marker.color}
                  fillOpacity={active ? 1 : 0.78}
                />
                <text
                  x={labelX}
                  y={labelY + 4}
                  textAnchor="middle"
                  fill="white"
                  fontSize="9"
                  fontFamily="monospace"
                  fontWeight="700"
                >
                  {marker.label}
                </text>
              </g>
            )
          })}
        </svg>

        {markers.length ? (
          <div className="mt-1 grid grid-cols-3 gap-2 font-mono-data text-[10px] text-muted-foreground/70">
            {markers.map((marker) => (
              <div key={`${marker.label}-distance`} className="flex items-center gap-1.5">
                <span className="font-semibold" style={{ color: marker.color }}>{marker.label}</span>
                <span>{Math.round(marker.distance)}m</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  )
}
