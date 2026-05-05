import { cn } from '@/lib/utils'

const tabs = ['Chat', 'Stats']

export default function TabBar({ activeTab, onTabChange }) {
  return (
    <div role="tablist" className="flex items-center gap-1">
      {tabs.map((tab) => (
        <button
          key={tab}
          role="tab"
          aria-selected={activeTab === tab}
          onClick={() => onTabChange(tab)}
          className={cn(
            'relative px-2.5 py-1.5 text-sm transition-colors',
            activeTab === tab
              ? 'text-foreground'
              : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {tab}
          {activeTab === tab ? (
            <span className="absolute inset-x-2 -bottom-[13px] h-px bg-primary" />
          ) : null}
        </button>
      ))}
    </div>
  )
}
