import { Badge } from './ui/badge.jsx'
import QualifyingBattleWidget from './chat-widgets/QualifyingBattleWidget.jsx'
import CornerAnalysisWidget from './chat-widgets/CornerAnalysisWidget.jsx'
import RaceStoryWidget from './chat-widgets/RaceStoryWidget.jsx'
import RacePaceBattleWidget from './chat-widgets/RacePaceBattleWidget.jsx'
import CornerComparisonWidget from './chat-widgets/CornerComparisonWidget.jsx'
import CircuitProfileWidget from './chat-widgets/CircuitProfileWidget.jsx'
import DataTableWidget from './chat-widgets/DataTableWidget.jsx'
import PitStopStrategyWidget from './chat-widgets/PitStopStrategyWidget.jsx'
import DegTrendChart from './chat-widgets/DegTrendChart.jsx'
import EnergyManagementWidget from './chat-widgets/EnergyManagementWidget.jsx'
import ActiveAeroWidget from './chat-widgets/ActiveAeroWidget.jsx'

function splitBlocks(text) {
  return text
    .trim()
    .split(/\n\s*\n/)
    .map((block) => block.trim())
    .filter(Boolean)
}

function isBullet(line) {
  return /^[-*]\s+/.test(line)
}

function isNumbered(line) {
  return /^\d+\.\s+/.test(line)
}

function isKeyValue(line) {
  return /^[A-Za-z][A-Za-z0-9 /&()+-]{1,28}:\s+.+$/.test(line)
}

function parseBlock(block) {
  const lines = block.split('\n').map((line) => line.trim()).filter(Boolean)
  if (lines.length === 0) return null

  if (lines.every(isBullet)) {
    return {
      type: 'bullet-list',
      items: lines.map((line) => line.replace(/^[-*]\s+/, '')),
    }
  }

  if (lines.every(isNumbered)) {
    return {
      type: 'number-list',
      items: lines.map((line) => line.replace(/^\d+\.\s+/, '')),
    }
  }

  if (lines.every(isKeyValue)) {
    return {
      type: 'kv-grid',
      rows: lines.map((line) => {
        const [label, ...rest] = line.split(':')
        return { label: label.trim(), value: rest.join(':').trim() }
      }),
    }
  }

  if (lines.length > 1 && !isBullet(lines[0]) && lines.slice(1).every(isBullet)) {
    return {
      type: 'section-list',
      title: lines[0].replace(/:$/, ''),
      items: lines.slice(1).map((line) => line.replace(/^[-*]\s+/, '')),
    }
  }

  return {
    type: 'paragraph',
    text: lines.join(' '),
  }
}

function renderInline(text, driverCodeSet) {
  const parts = text.split(
    /(\*\*\*[^*]+\*\*\*|\*\*[^*]+\*\*|`[^`]+`|\bP\d+\b|\bQ[123]\b|\bSC\b|\bVSC\b|\bFP[123]\b|\b[A-Z]{3}\b|\b\d+\.\d+s\b)/g,
  )

  return parts.map((part, index) => {
    if (!part) return null

    if (/^\*\*\*[^*]+\*\*\*$/.test(part)) {
      return <strong key={index} className="font-semibold text-foreground">{part.slice(3, -3)}</strong>
    }

    if (/^\*\*[^*]+\*\*$/.test(part)) {
      return <strong key={index} className="font-semibold text-foreground">{part.slice(2, -2)}</strong>
    }

    if (/^`[^`]+`$/.test(part)) {
      return (
        <code key={index} className="rounded-sm border border-border bg-background px-1.5 py-0.5 text-[0.92em] text-foreground">
          {part.slice(1, -1)}
        </code>
      )
    }

    if (/^P\d+$/.test(part)) {
      return <Badge key={index} variant="default" className="mx-0.5 normal-case tracking-normal">{part}</Badge>
    }

    if (/^(SC|VSC|Q[123]|FP[123])$/.test(part)) {
      return <Badge key={index} variant="default" className="mx-0.5 normal-case tracking-normal">{part}</Badge>
    }

    if (/^[A-Z]{3}$/.test(part) && driverCodeSet && driverCodeSet.has(part)) {
      return <Badge key={index} variant="muted" className="mx-0.5 tracking-[0.08em]">{part}</Badge>
    }

    if (/^\d+\.\d+s$/.test(part)) {
      return (
        <span key={index} className="font-mono-data font-medium" style={{ color: 'hsl(var(--time))' }}>
          {part}
        </span>
      )
    }

    return <span key={index}>{part}</span>
  })
}

function List({ items, ordered = false, driverCodeSet }) {
  const Tag = ordered ? 'ol' : 'ul'

  return (
    <Tag className={ordered ? 'space-y-2 pl-5 text-[15px] leading-7 text-foreground list-decimal' : 'space-y-2 pl-5 text-[15px] leading-7 text-foreground list-disc'}>
      {items.map((item, index) => (
        <li key={index}>{renderInline(item, driverCodeSet)}</li>
      ))}
    </Tag>
  )
}

function WidgetRenderer({ widget }) {
  if (!widget?.type) return null
  if (widget.type === 'qualifying_battle') {
    return <QualifyingBattleWidget widget={widget} />
  }
  if (widget.type === 'corner_analysis') {
    return <CornerAnalysisWidget widget={widget} />
  }
  if (widget.type === 'race_story') {
    return <RaceStoryWidget widget={widget} />
  }
  if (widget.type === 'race_pace_battle') {
    return <RacePaceBattleWidget widget={widget} />
  }
  if (widget.type === 'corner_comparison') {
    return <CornerComparisonWidget widget={widget} />
  }
  if (widget.type === 'circuit_profile') {
    return <CircuitProfileWidget widget={widget} />
  }
  if (widget.type === 'data_table') {
    return <DataTableWidget widget={widget} />
  }
  if (widget.type === 'pit_stop_strategy') {
    return <PitStopStrategyWidget widget={widget} />
  }
  if (widget.type === 'deg_trend_chart') {
    return <DegTrendChart widget={widget} />
  }
  if (widget.type === 'energy_management') {
    return <EnergyManagementWidget widget={widget} />
  }
  if (widget.type === 'active_aero') {
    return <ActiveAeroWidget widget={widget} />
  }
  return null
}

export default function AnswerRenderer({ text, widgets = [], validDriverCodes }) {
  const blocks = splitBlocks(text).map(parseBlock).filter(Boolean)
  if (blocks.length === 0 && widgets.length === 0) return null

  const driverCodeSet = Array.isArray(validDriverCodes) && validDriverCodes.length > 0
    ? new Set(validDriverCodes)
    : null

  const [first, ...rest] = blocks
  const hasLead = first?.type === 'paragraph'
  const bodyBlocks = hasLead ? rest : blocks

  return (
    <div className="max-w-3xl space-y-5">
      {hasLead ? (
        <p className="text-[15px] leading-7 text-foreground">
          {renderInline(first.text, driverCodeSet)}
        </p>
      ) : null}

      {widgets.map((widget, index) => (
        <div
          key={widget._id ?? `${widget.type}-${index}`}
          className={index === 0 ? 'widget-enter' : index === 1 ? 'widget-enter-1' : 'widget-enter-2'}
        >
          <WidgetRenderer widget={widget} />
        </div>
      ))}

      {bodyBlocks.map((block, index) => {
        if (block.type === 'paragraph') {
          return (
            <p key={index} className="text-[15px] leading-7 text-foreground">
              {renderInline(block.text, driverCodeSet)}
            </p>
          )
        }

        if (block.type === 'bullet-list') {
          return <List key={index} items={block.items} driverCodeSet={driverCodeSet} />
        }

        if (block.type === 'number-list') {
          return <List key={index} items={block.items} ordered driverCodeSet={driverCodeSet} />
        }

        if (block.type === 'kv-grid') {
          return (
            <dl key={index} className="space-y-0 border-y border-border/70 py-1">
              {block.rows.map((row, rowIndex) => (
                <div
                  key={rowIndex}
                  className="grid gap-1 border-b border-border/60 py-3 last:border-b-0 sm:grid-cols-[8rem_minmax(0,1fr)] sm:gap-4"
                >
                  <dt className="text-sm font-medium text-muted-foreground">{row.label}</dt>
                  <dd className="text-[15px] leading-7 text-foreground">{renderInline(row.value, driverCodeSet)}</dd>
                </div>
              ))}
            </dl>
          )
        }

        if (block.type === 'section-list') {
          return (
            <section key={index} className="space-y-3">
              <h3 className="text-[15px] font-semibold text-foreground">{block.title}</h3>
              <List items={block.items} driverCodeSet={driverCodeSet} />
            </section>
          )
        }

        return null
      })}
    </div>
  )
}
