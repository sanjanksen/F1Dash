// client/src/App.jsx
import { useState, useEffect } from 'react'
import TabBar from './components/TabBar.jsx'
import StatsView from './components/StatsView.jsx'
import ChatView from './components/ChatView.jsx'
import Sidebar from './components/Sidebar.jsx'
import { useChatSessions } from './hooks/useChatSessions.js'
import { sendChatMessage } from './api/f1api.js'
import './App.css'

export default function App() {
  const [activeTab, setActiveTab] = useState('Chat')
  const [loading, setLoading] = useState(false)
  const year = new Date().getFullYear()

  const {
    sessions,
    activeId,
    activeSession,
    setActiveId,
    createSession,
    updateMessages,
    deleteSession,
  } = useChatSessions()

  // Always have at least one session
  useEffect(() => {
    if (sessions.length === 0) createSession()
  }, [sessions.length, createSession])

  const handleSend = async (text) => {
    let sessionId = activeId
    if (!sessionId) sessionId = createSession()

    const current = activeSession?.messages || []
    const withUser = [...current, { id: crypto.randomUUID(), role: 'user', text }]
    updateMessages(sessionId, withUser)
    setLoading(true)

    // Send prior messages as history so the model has conversation context
    const history = current.map(m => ({ role: m.role, content: m.text }))

    try {
      const { response } = await sendChatMessage(text, history)
      updateMessages(sessionId, [
        ...withUser,
        { id: crypto.randomUUID(), role: 'assistant', text: response },
      ])
    } catch (e) {
      updateMessages(sessionId, [
        ...withUser,
        { id: crypto.randomUUID(), role: 'assistant', text: `Something went wrong: ${e.message}`, isError: true },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="header-sidebar-zone">
          <div className="brand-block">
            <span className="f1-wordmark">F<span>1</span> Dash</span>
            <span className="brand-subtitle">{year} live analysis workspace</span>
          </div>
          <button
            className="sidebar-new-btn"
            onClick={createSession}
            aria-label="New chat"
            title="New chat"
          >
            <svg viewBox="0 0 16 16" fill="none" width="13" height="13">
              <path d="M8 2v12M2 8h12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="header-main-zone">
          <div className="header-status">
            <span className="status-dot" />
            <span>FastF1-backed race intelligence</span>
          </div>
          <TabBar activeTab={activeTab} onTabChange={setActiveTab} />
        </div>
      </header>
      <main className="app-main">
        <div className={`view-pane${activeTab === 'Stats' ? ' view-active view-stats' : ' view-stats'}`}>
          <StatsView />
        </div>
        <div className={`view-pane${activeTab === 'Chat' ? ' view-active view-chat' : ' view-chat'}`}>
          <div className="chat-layout">
            <Sidebar
              sessions={sessions}
              activeId={activeId}
              onSelect={setActiveId}
              onNew={createSession}
              onDelete={deleteSession}
            />
            <ChatView
              messages={activeSession?.messages || []}
              loading={loading}
              onSend={handleSend}
            />
          </div>
        </div>
      </main>
    </div>
  )
}
