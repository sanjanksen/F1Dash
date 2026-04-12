import { useCallback, useEffect, useState } from 'react'

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
    const stored = load()
    return stored.length > 0 ? stored[0].id : null
  })

  useEffect(() => {
    if (activeId && !sessions.find((session) => session.id === activeId)) {
      setActiveId(sessions.length > 0 ? sessions[0].id : null)
    }
  }, [sessions, activeId])

  const createSession = useCallback(() => {
    const id = crypto.randomUUID()
    const session = { id, title: 'New Chat', messages: [], createdAt: Date.now() }

    setSessions((prev) => {
      const next = [session, ...prev]
      persist(next)
      return next
    })

    setActiveId(id)
    return id
  }, [])

  const updateMessages = useCallback((id, messages) => {
    setSessions((prev) => {
      const next = prev.map((session) => {
        if (session.id !== id) return session

        const firstUser = messages.find((message) => message.role === 'user')
        const title = firstUser
          ? firstUser.text.slice(0, 44) + (firstUser.text.length > 44 ? '...' : '')
          : 'New Chat'

        return { ...session, title, messages }
      })

      persist(next)
      return next
    })
  }, [])

  const deleteSession = useCallback((id) => {
    setSessions((prev) => {
      const next = prev.filter((session) => session.id !== id)
      persist(next)
      return next
    })
  }, [])

  const activeSession = sessions.find((session) => session.id === activeId) ?? null

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
