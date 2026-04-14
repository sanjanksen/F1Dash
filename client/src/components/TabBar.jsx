import { cn } from '@/lib/utils'

const tabs = ['Stats', 'Chat']

export default function TabBar({ activeTab, onTabChange }) {
  return (
    <div
      role="tablist"
      className="inline-flex items-center rounded-md border border-border bg-card p-1"
    >
      {tabs.map((tab) => (
        <button
          key={tab}
          role="tab"
          aria-selected={activeTab === tab}
          onClick={() => onTabChange(tab)}
          className={cn(
            'rounded-sm px-3 py-1.5 text-xs font-medium tracking-[0.12em] uppercase transition-colors',
            activeTab === tab
              ? 'bg-primary/15 text-primary ring-1 ring-inset ring-primary/25'
              : 'text-muted-foreground hover:text-foreground hover:bg-secondary/60',
          )}
        >
          {tab}
        </button>
      ))}
    </div>
  )
}
