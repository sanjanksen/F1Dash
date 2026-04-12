// client/src/App.jsx
import { useState } from 'react'
import TabBar from './components/TabBar.jsx'
import StatsView from './components/StatsView.jsx'
import ChatView from './components/ChatView.jsx'
import './App.css'

export default function App() {
  const [activeTab, setActiveTab] = useState('Stats')

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="header-inner">
          <div className="header-brand">
            <span className="f1-wordmark">F<span>1</span></span>
            <span className="header-subtitle">Dashboard</span>
          </div>
          <TabBar activeTab={activeTab} onTabChange={setActiveTab} />
        </div>
      </header>
      <main className="app-main">
        <div hidden={activeTab !== 'Stats'}><StatsView /></div>
        <div hidden={activeTab !== 'Chat'}><ChatView /></div>
      </main>
    </div>
  )
}
