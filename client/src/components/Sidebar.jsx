// client/src/components/Sidebar.jsx

function formatDate(ts) {
  const d = new Date(ts)
  const now = new Date()
  if (d.toDateString() === now.toDateString()) return 'Today'
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (d.toDateString() === yesterday.toDateString()) return 'Yesterday'
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export default function Sidebar({ sessions, activeId, onSelect, onNew, onDelete }) {
  // Group sessions by date label
  const groups = []
  const seen = new Set()
  for (const s of sessions) {
    const label = formatDate(s.createdAt)
    if (!seen.has(label)) {
      seen.add(label)
      groups.push({ label, items: [s] })
    } else {
      groups[groups.length - 1].items.push(s)
    }
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-sessions">
        {sessions.length === 0 && (
          <p className="sidebar-empty">No chats yet</p>
        )}
        {groups.map(group => (
          <div key={group.label} className="session-group">
            <span className="session-group-label">{group.label}</span>
            {group.items.map(s => (
              <div
                key={s.id}
                className={`session-item${s.id === activeId ? ' active' : ''}`}
                onClick={() => onSelect(s.id)}
              >
                <span className="session-title">{s.title}</span>
                <button
                  className="session-delete"
                  onClick={e => { e.stopPropagation(); onDelete(s.id) }}
                  aria-label="Delete chat"
                >
                  <svg viewBox="0 0 12 12" fill="none" width="9" height="9">
                    <path d="M1 1l10 10M11 1L1 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        ))}
      </div>
    </aside>
  )
}
