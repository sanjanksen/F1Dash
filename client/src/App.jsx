import { useEffect, useState } from 'react'
import { Plus } from 'lucide-react'

import { sendChatMessage } from './api/f1api.js'
import ChatView from './components/ChatView.jsx'
import Sidebar from './components/Sidebar.jsx'
import StatsView from './components/StatsView.jsx'
import TabBar from './components/TabBar.jsx'
import { Button } from './components/ui/button.jsx'
import { useChatSessions } from './hooks/useChatSessions.js'

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

    const history = current.map((message) => ({ role: message.role, content: message.text }))

    try {
      const { response, widgets = [] } = await sendChatMessage(text, history)
      updateMessages(sessionId, [
        ...withUser,
        { id: crypto.randomUUID(), role: 'assistant', text: response, widgets },
      ])
    } catch (error) {
      updateMessages(sessionId, [
        ...withUser,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          text: `Something went wrong: ${error.message}`,
          isError: true,
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="dark h-full bg-background text-foreground">
      <div className="flex h-full flex-col">
        {/* Speed stripe — shimmer sweep */}
        <div
          className="h-[3px] w-full shrink-0"
          style={{
            background: 'linear-gradient(90deg, hsl(var(--primary)/0.4) 0%, hsl(var(--primary)) 25%, hsl(38 95% 62%) 50%, hsl(var(--primary)) 75%, hsl(var(--primary)/0.4) 100%)',
            backgroundSize: '200% 100%',
            animation: 'shimmer 5s linear infinite',
          }}
        />
        <header className="border-b border-border/90 bg-background/95 backdrop-blur-sm">
          <div className="grid h-12 grid-cols-1 md:grid-cols-[16rem_minmax(0,1fr)]">
            <div className="hidden items-center justify-between border-r border-border/90 px-4 md:flex">
              <div className="min-w-0">
                <div className="font-display text-base font-semibold tracking-tight text-foreground" style={{ letterSpacing: '-0.01em' }}>
                  <span className="text-primary">F1</span>{' '}
                  <span className="text-foreground">Dash</span>
                </div>
                <div className="mt-0.5 text-[9px] uppercase tracking-[0.22em] text-muted-foreground/80">
                  {year} race intelligence
                </div>
              </div>
              <Button
                variant="outline"
                size="icon"
                onClick={createSession}
                aria-label="New chat"
                title="New chat"
                className="h-7 w-7"
              >
                <Plus className="h-3.5 w-3.5" />
              </Button>
            </div>

            <div className="flex items-center justify-between gap-3 px-4 md:px-5">
              <div className="flex min-w-0 items-center gap-2 text-[11px] text-muted-foreground">
                <span className="live-dot" />
                <span className="truncate uppercase tracking-[0.12em]">FastF1-backed analysis</span>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="icon"
                  onClick={createSession}
                  aria-label="New chat"
                  className="h-8 w-8 md:hidden"
                >
                  <Plus className="h-4 w-4" />
                </Button>
                <TabBar activeTab={activeTab} onTabChange={setActiveTab} />
              </div>
            </div>
          </div>
        </header>

        <main className="flex min-h-0 flex-1 overflow-hidden">
          <section className={activeTab === 'Stats' ? 'flex min-h-0 flex-1 overflow-y-auto' : 'hidden min-h-0 flex-1'}>
            <StatsView />
          </section>

          <section className={activeTab === 'Chat' ? 'flex min-h-0 flex-1 overflow-hidden' : 'hidden min-h-0 flex-1'}>
            <div className="flex min-h-0 flex-1 overflow-hidden">
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
          </section>
        </main>
      </div>
    </div>
  )
}
