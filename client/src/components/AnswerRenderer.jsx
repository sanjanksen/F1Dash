function splitBlocks(text) {
  return text
    .trim()
    .split(/\n\s*\n/)
    .map(block => block.trim())
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
  const lines = block.split('\n').map(line => line.trim()).filter(Boolean)
  if (lines.length === 0) return null

  if (lines.every(isBullet)) {
    return {
      type: 'bullet-list',
      items: lines.map(line => line.replace(/^[-*]\s+/, '')),
    }
  }

  if (lines.every(isNumbered)) {
    return {
      type: 'number-list',
      items: lines.map(line => line.replace(/^\d+\.\s+/, '')),
    }
  }

  if (lines.every(isKeyValue)) {
    return {
      type: 'kv-grid',
      rows: lines.map(line => {
        const [label, ...rest] = line.split(':')
        return { label: label.trim(), value: rest.join(':').trim() }
      }),
    }
  }

  if (lines.length > 1 && !isBullet(lines[0]) && lines.slice(1).every(isBullet)) {
    return {
      type: 'section-list',
      title: lines[0].replace(/:$/, ''),
      items: lines.slice(1).map(line => line.replace(/^[-*]\s+/, '')),
    }
  }

  return {
    type: 'paragraph',
    text: lines.join(' '),
  }
}

function renderInline(text) {
  const parts = text.split(/(\*\*\*[^*]+\*\*\*|\*\*[^*]+\*\*|`[^`]+`|\bP\d+\b|\bQ[123]\b|\bSC\b|\bVSC\b|\bFP[123]\b|\b[A-Z]{3}\b|\b\d+\.\d+s\b)/g)
  return parts.map((part, index) => {
    if (!part) return null
    if (/^\*\*\*[^*]+\*\*\*$/.test(part)) {
      const value = part.slice(3, -3)
      return <strong key={index} className="inline-strong">{value}</strong>
    }
    if (/^\*\*[^*]+\*\*$/.test(part)) {
      const value = part.slice(2, -2)
      return <strong key={index} className="inline-strong">{value}</strong>
    }
    if (/^`[^`]+`$/.test(part)) {
      return <code key={index} className="inline-code">{part.slice(1, -1)}</code>
    }
    if (/^P\d+$/.test(part)) {
      return <span key={index} className="inline-pill position-pill">{part}</span>
    }
    if (/^(SC|VSC|Q[123]|FP[123])$/.test(part)) {
      return <span key={index} className="inline-pill session-pill">{part}</span>
    }
    if (/^[A-Z]{3}$/.test(part)) {
      return <span key={index} className="inline-pill code-pill">{part}</span>
    }
    if (/^\d+\.\d+s$/.test(part)) {
      return <span key={index} className="inline-time">{part}</span>
    }
    return <span key={index}>{part}</span>
  })
}

export default function AnswerRenderer({ text }) {
  const blocks = splitBlocks(text).map(parseBlock).filter(Boolean)
  if (blocks.length === 0) return null

  const [first, ...rest] = blocks
  const hasLead = first?.type === 'paragraph'

  return (
    <div className="answer-renderer">
      {hasLead && (
        <div className="answer-lead">
          <p>{renderInline(first.text)}</p>
        </div>
      )}

      <div className="answer-blocks">
        {(hasLead ? rest : blocks).map((block, index) => {
          if (block.type === 'paragraph') {
            return (
              <div key={index} className="answer-card prose-card">
                <p>{renderInline(block.text)}</p>
              </div>
            )
          }

          if (block.type === 'bullet-list') {
            return (
              <div key={index} className="answer-card list-card">
                <ul className="answer-list">
                  {block.items.map((item, itemIndex) => (
                    <li key={itemIndex}>{renderInline(item)}</li>
                  ))}
                </ul>
              </div>
            )
          }

          if (block.type === 'number-list') {
            return (
              <div key={index} className="answer-card list-card">
                <ol className="answer-list ordered">
                  {block.items.map((item, itemIndex) => (
                    <li key={itemIndex}>{renderInline(item)}</li>
                  ))}
                </ol>
              </div>
            )
          }

          if (block.type === 'kv-grid') {
            return (
              <div key={index} className="answer-card kv-card">
                <div className="kv-grid">
                  {block.rows.map((row, rowIndex) => (
                    <div key={rowIndex} className="kv-row">
                      <span className="kv-label">{row.label}</span>
                      <span className="kv-value">{renderInline(row.value)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )
          }

          if (block.type === 'section-list') {
            return (
              <div key={index} className="answer-card section-card">
                <div className="section-card-head">
                  <span className="section-kicker">Section</span>
                  <h4>{block.title}</h4>
                </div>
                <ul className="answer-list">
                  {block.items.map((item, itemIndex) => (
                    <li key={itemIndex}>{renderInline(item)}</li>
                  ))}
                </ul>
              </div>
            )
          }

          return null
        })}
      </div>
    </div>
  )
}
