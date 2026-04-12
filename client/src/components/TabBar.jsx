// client/src/components/TabBar.jsx
export default function TabBar({ activeTab, onTabChange }) {
  const tabs = ['Stats', 'Chat']
  return (
    <div className="header-tabs" role="tablist">
      {tabs.map(tab => (
        <button
          key={tab}
          role="tab"
          aria-selected={activeTab === tab}
          className={`tab-btn${activeTab === tab ? ' active' : ''}`}
          onClick={() => onTabChange(tab)}
        >
          {tab}
        </button>
      ))}
    </div>
  )
}
