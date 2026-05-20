import { useEffect, useState } from 'react'
import { Moon, PanelLeftClose, PanelLeftOpen, Plus, Sun } from 'lucide-react'

import { sendChatMessage } from './api/f1api.js'
import ChatView from './components/ChatView.jsx'
import Sidebar from './components/Sidebar.jsx'
import { Button } from './components/ui/button.jsx'
import { useChatSessions } from './hooks/useChatSessions.js'

function validateChatResponse(body) {
  if (!body || typeof body !== 'object') {
    return { ok: false, reason: 'not-an-object' }
  }
  if (typeof body.response !== 'string' || body.response.length === 0) {
    return { ok: false, reason: 'missing-or-empty-response' }
  }
  if (body.widgets != null && !Array.isArray(body.widgets)) {
    return { ok: false, reason: 'widgets-not-array' }
  }
  return { ok: true, response: body.response, widgets: body.widgets ?? [] }
}

function getInitialTheme() {
  const stored = localStorage.getItem('f1dash-theme')
  if (stored === 'light' || stored === 'dark') return stored
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export default function App() {
  const [loading, setLoading] = useState(false)
  const [theme, setTheme] = useState(getInitialTheme)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

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

  useEffect(() => {
    localStorage.setItem('f1dash-theme', theme)
  }, [theme])

  const handleSend = async (text) => {
    let sessionId = activeId
    if (!sessionId) sessionId = createSession()

    const current = activeSession?.messages || []
    const withUser = [...current, { id: crypto.randomUUID(), role: 'user', text }]
    updateMessages(sessionId, withUser)
    setLoading(true)

    const history = current.map((message) => ({ role: message.role, content: message.text }))

    try {
      const body = await sendChatMessage(text, history)
      const validated = validateChatResponse(body)
      if (!validated.ok) {
        console.error('Chat response shape invalid:', validated.reason, body)
        updateMessages(sessionId, [
          ...withUser,
          {
            id: crypto.randomUUID(),
            role: 'assistant',
            text: 'The server returned an unexpected response. Please try again.',
            isError: true,
          },
        ])
        return
      }

      const { response, widgets } = validated
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

  const isDark = theme === 'dark'

  return (
    <div className={`${isDark ? 'dark' : ''} h-full bg-background text-foreground`}>
      <div className="flex h-full flex-col">
        <header className="shell-hairline flex h-14 shrink-0 items-center justify-between px-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-4">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setSidebarCollapsed((value) => !value)}
              aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              className="hidden h-9 w-9 md:inline-flex"
            >
              {sidebarCollapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
            </Button>
            <div className="text-[15px] font-medium tracking-[-0.015em] text-muted-foreground">Chat</div>
          </div>

          <div className="flex items-center gap-1.5">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setTheme(isDark ? 'light' : 'dark')}
              aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
              title={isDark ? 'Light mode' : 'Dark mode'}
              className="h-9 w-9"
            >
              {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={createSession}
              aria-label="New chat"
              title="New chat"
              className="h-9 w-9"
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        </header>

        <main className="flex min-h-0 flex-1 overflow-hidden">
          <Sidebar
            sessions={sessions}
            activeId={activeId}
            onSelect={setActiveId}
            onNew={createSession}
            onDelete={deleteSession}
            collapsed={sidebarCollapsed}
          />
          <ChatView
            messages={activeSession?.messages || []}
            loading={loading}
            onSend={handleSend}
          />
        </main>
      </div>
    </div>
  )
}
