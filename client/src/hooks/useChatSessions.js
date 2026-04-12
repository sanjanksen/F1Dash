// client/src/hooks/useChatSessions.js
import { useState, useCallback, useEffect } from 'react'

const STORAGE_KEY = 'f1dash_sessions'

function load() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
  } catch {
    return []
  }
}

function persist(sessions) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions))
}

export function useChatSessions() {
  const [sessions, setSessions] = useState(load)
  const [activeId, setActiveId] = useState(() => {
    const s = load()
    return s.length > 0 ? s[0].id : null
  })

  // If active session was deleted, fall back to first remaining
  useEffect(() => {
    if (activeId && !sessions.find(s => s.id === activeId)) {
      setActiveId(sessions.length > 0 ? sessions[0].id : null)
    }
  }, [sessions, activeId])

  const createSession = useCallback(() => {
    const id = crypto.randomUUID()
    const session = { id, title: 'New Chat', messages: [], createdAt: Date.now() }
    setSessions(prev => {
      const next = [session, ...prev]
      persist(next)
      return next
    })
    setActiveId(id)
    return id
  }, [])

  const updateMessages = useCallback((id, messages) => {
    setSessions(prev => {
      const next = prev.map(s => {
        if (s.id !== id) return s
        const firstUser = messages.find(m => m.role === 'user')
        const title = firstUser
          ? firstUser.text.slice(0, 44) + (firstUser.text.length > 44 ? '…' : '')
          : 'New Chat'
        return { ...s, title, messages }
      })
      persist(next)
      return next
    })
  }, [])

  const deleteSession = useCallback((id) => {
    setSessions(prev => {
      const next = prev.filter(s => s.id !== id)
      persist(next)
      return next
    })
  }, [])

  const activeSession = sessions.find(s => s.id === activeId) ?? null

  return {
    sessions,
    activeId,
    activeSession,
    setActiveId,
    createSession,
    updateMessages,
    deleteSession,
  }
}
