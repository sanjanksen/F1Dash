// client/src/components/TabBar.jsx
export default function TabBar({ activeTab, onTabChange }) {
  const tabs = ['Stats', 'Chat']
  return (
    <div className="header-tabs">
      {tabs.map(tab => (
        <button
          key={tab}
          className={`tab-btn${activeTab === tab ? ' active' : ''}`}
          onClick={() => onTabChange(tab)}
        >
          {tab}
        </button>
      ))}
    </div>
  )
}
