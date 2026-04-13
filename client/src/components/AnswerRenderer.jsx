import { Badge } from './ui/badge.jsx'
import { Card, CardContent } from './ui/card.jsx'
import QualifyingBattleWidget from './chat-widgets/QualifyingBattleWidget.jsx'
import RaceStoryWidget from './chat-widgets/RaceStoryWidget.jsx'

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

const BADGE_BLOCKLIST = new Set([
    'LAP', 'WET', 'DRY', 'FIA', 'ERS', 'PIT', 'CAR', 'RUN', 'END',
    'ALL', 'THE', 'AND', 'FOR', 'BUT', 'NOT', 'NEW', 'OLD', 'TOP',
    'ONE', 'TWO', 'SET', 'BOX', 'OFF', 'OWN', 'WAY', 'PUT', 'GET',
    'GOT', 'HAD', 'HAS', 'WAS', 'CAN', 'DID', 'NOW', 'ITS', 'OUT',
    'WIN', 'LED', 'GAP', 'AIR', 'KPH', 'MPH', 'KMH', 'TYR', 'AGO',
])

function renderInline(text) {
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

    if (/^[A-Z]{3}$/.test(part) && !BADGE_BLOCKLIST.has(part)) {
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

function List({ items, ordered = false }) {
  const Tag = ordered ? 'ol' : 'ul'

  return (
    <Tag className={ordered ? 'space-y-1.5 pl-5 text-sm leading-7 text-foreground list-decimal' : 'space-y-1.5 pl-5 text-sm leading-7 text-foreground list-disc'}>
      {items.map((item, index) => (
        <li key={index}>{renderInline(item)}</li>
      ))}
    </Tag>
  )
}

function WidgetRenderer({ widget }) {
  if (!widget?.type) return null
  if (widget.type === 'qualifying_battle') {
    return <QualifyingBattleWidget widget={widget} />
  }
  if (widget.type === 'race_story') {
    return <RaceStoryWidget widget={widget} />
  }
  return null
}

export default function AnswerRenderer({ text, widgets = [] }) {
  const blocks = splitBlocks(text).map(parseBlock).filter(Boolean)
  if (blocks.length === 0 && widgets.length === 0) return null

  const [first, ...rest] = blocks
  const hasLead = first?.type === 'paragraph'
  const bodyBlocks = hasLead ? rest : blocks

  return (
    <div className="max-w-3xl space-y-3.5">
      {hasLead ? (
        <div className="text-[15px] leading-7 text-foreground">
          {renderInline(first.text)}
        </div>
      ) : null}

      {widgets.map((widget, index) => (
        <div
          key={`${widget.type}-${index}`}
          className={index === 0 ? 'widget-enter' : index === 1 ? 'widget-enter-1' : 'widget-enter-2'}
        >
          <WidgetRenderer widget={widget} />
        </div>
      ))}

      {bodyBlocks.map((block, index) => {
        if (block.type === 'paragraph') {
          return (
            <Card key={index}>
              <CardContent className="p-4 text-sm leading-7 text-foreground">
                {renderInline(block.text)}
              </CardContent>
            </Card>
          )
        }

        if (block.type === 'bullet-list') {
          return (
            <Card key={index}>
              <CardContent className="p-4">
                <List items={block.items} />
              </CardContent>
            </Card>
          )
        }

        if (block.type === 'number-list') {
          return (
            <Card key={index}>
              <CardContent className="p-4">
                <List items={block.items} ordered />
              </CardContent>
            </Card>
          )
        }

        if (block.type === 'kv-grid') {
          return (
            <Card key={index}>
              <CardContent className="grid gap-3 p-4">
                {block.rows.map((row, rowIndex) => (
                  <div
                    key={rowIndex}
                    className="grid gap-1 border-b border-border/80 pb-3 last:border-b-0 last:pb-0 sm:grid-cols-[9rem_minmax(0,1fr)] sm:gap-4"
                  >
                    <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                      {row.label}
                    </div>
                    <div className="text-sm leading-7 text-foreground">{renderInline(row.value)}</div>
                  </div>
                ))}
              </CardContent>
            </Card>
          )
        }

        if (block.type === 'section-list') {
          return (
            <Card key={index}>
              <CardContent className="p-4">
                <div className="mb-3 text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                  {block.title}
                </div>
                <List items={block.items} />
              </CardContent>
            </Card>
          )
        }

        return null
      })}
    </div>
  )
}
