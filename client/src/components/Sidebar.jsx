import { MessageSquareText, Plus, Trash2 } from 'lucide-react'

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

export default function Sidebar({ sessions, activeId, onSelect, onNew, onDelete, collapsed = false }) {
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
    <aside
      className={cn(
        'sidebar-shell hidden h-full shrink-0 bg-sidebar text-sidebar-foreground transition-[width] duration-150 md:flex md:flex-col',
        collapsed ? 'w-[4.5rem]' : 'w-[17.25rem]',
      )}
    >
      <div className={cn('px-4 pb-3 pt-4', collapsed && 'px-3')}>
        <div className={cn('mb-3 flex items-center justify-between gap-3', collapsed && 'justify-center')}>
          {collapsed ? (
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-sidebar-active text-sm font-semibold text-foreground">
              F1
            </div>
          ) : (
            <div>
              <div className="text-sm font-semibold tracking-[-0.01em]">F1Dash</div>
              <div className="mt-0.5 text-xs text-muted-foreground">Race intelligence</div>
            </div>
          )}
        </div>

        <button
          type="button"
          onClick={onNew}
          className={cn(
            'flex h-9 w-full items-center justify-between rounded-lg border border-border/80 bg-sidebar-active text-sm font-medium text-foreground transition-colors hover:border-border hover:bg-background',
            collapsed ? 'justify-center px-0' : 'px-3',
          )}
          aria-label="New chat"
          title="New chat"
        >
          {collapsed ? null : <span>New chat</span>}
          <Plus className="h-4 w-4 text-muted-foreground" />
        </button>
      </div>

      <div className={cn('border-t border-border/70 px-4 py-3', collapsed && 'px-3')}>
        <div className="text-xs font-medium text-muted-foreground">History</div>
      </div>

      <div className={cn('app-scrollbar min-h-0 flex-1 overflow-y-auto px-2 pb-4', collapsed && 'px-3')}>
        {sessions.length === 0 ? (
          <div className={cn('mx-2 rounded-lg border border-dashed border-border/80 px-3 py-4 text-sm leading-6 text-muted-foreground', collapsed && 'mx-0 px-0 text-center text-xs')}>
            No chats yet.
          </div>
        ) : (
          groups.map((group) => (
            <div key={group.label} className="mb-5">
              {collapsed ? null : <div className="px-2 pb-1.5 text-xs font-medium text-muted-foreground">{group.label}</div>}
              <div className="space-y-1">
                {group.items.map((session) => {
                  const isActive = session.id === activeId
                  return (
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
                      className={cn(
                        'group flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors',
                        collapsed && 'justify-center px-0',
                        isActive
                          ? 'bg-sidebar-active text-foreground'
                          : 'text-muted-foreground hover:bg-sidebar-active/70 hover:text-foreground',
                      )}
                      title={collapsed ? session.title : undefined}
                    >
                      <span
                        className={cn(
                          'flex h-7 w-7 shrink-0 items-center justify-center rounded-md border',
                          isActive
                            ? 'border-primary/25 bg-primary/10 text-primary'
                            : 'border-border/70 bg-background/35 text-muted-foreground',
                        )}
                      >
                        <MessageSquareText className="h-3.5 w-3.5" />
                      </span>
                      {collapsed ? null : <span className="min-w-0 flex-1 truncate text-sm">{session.title}</span>}
                      <button
                        type="button"
                        className={cn(
                          'inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:bg-secondary hover:text-foreground',
                          collapsed && 'hidden',
                        )}
                        onClick={(event) => {
                          event.stopPropagation()
                          onDelete(session.id)
                        }}
                        aria-label="Delete chat"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  )
                })}
              </div>
            </div>
          ))
        )}
      </div>
    </aside>
  )
}
