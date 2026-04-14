import { MessageSquareText, Trash2 } from 'lucide-react'

import { cn } from '@/lib/utils'

function formatDate(timestamp) {
  const date = new Date(timestamp)
  const now = new Date()

  if (date.toDateString() === now.toDateString()) return 'Today'

  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday'

  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export default function Sidebar({ sessions, activeId, onSelect, onDelete }) {
  const groups = []
  const seen = new Set()

  for (const session of sessions) {
    const label = formatDate(session.createdAt)
    if (!seen.has(label)) {
      seen.add(label)
      groups.push({ label, items: [session] })
    } else {
      groups.find((g) => g.label === label).items.push(session)
    }
  }

  return (
    <aside className="hidden h-full w-[16rem] shrink-0 border-r border-border/90 bg-background md:flex md:flex-col">
      <div className="border-b border-border/90 px-4 py-3">
        <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
          Chat Sessions
        </div>
      </div>

      <div className="app-scrollbar min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {sessions.length === 0 ? (
          <div className="rounded-md border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground">
            No chats yet.
          </div>
        ) : (
          groups.map((group) => (
            <div key={group.label} className="mb-5">
              <div className="px-2 pb-2 text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                {group.label}
              </div>
              <div className="space-y-1">
                {group.items.map((session) => (
                  <div
                    key={session.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => onSelect(session.id)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        onSelect(session.id)
                      }
                    }}
                    style={session.id === activeId
                      ? { boxShadow: 'inset 2px 0 0 hsl(var(--primary) / 0.8)' }
                      : undefined}
                    className={cn(
                      'group flex w-full cursor-pointer items-center gap-3 rounded-md border px-3 py-2 text-left transition-all duration-150',
                      session.id === activeId
                        ? 'border-border/80 bg-card text-foreground'
                        : 'border-transparent text-muted-foreground hover:border-border/60 hover:bg-card/80 hover:text-foreground',
                    )}
                  >
                    <MessageSquareText className="h-4 w-4 shrink-0" />
                    <span className="min-w-0 flex-1 truncate text-sm">
                      {session.title}
                    </span>
                    <button
                      type="button"
                      className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:bg-secondary hover:text-foreground"
                      onClick={(event) => {
                        event.stopPropagation()
                        onDelete(session.id)
                      }}
                      aria-label="Delete chat"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ))
        )}
      </div>
    </aside>
  )
}
