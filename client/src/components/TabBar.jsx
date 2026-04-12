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
              ? 'bg-secondary text-foreground'
              : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {tab}
        </button>
      ))}
    </div>
  )
}
