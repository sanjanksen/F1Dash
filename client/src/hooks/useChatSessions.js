import { useCallback, useEffect, useState } from 'react'

const STORAGE_KEY = 'f1dash_sessions'
const TARGET_BYTES = 4 * 1024 * 1024
const MIN_SESSIONS_TO_KEEP = 5

function load() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
  } catch {
    return []
  }
}

function approxBytes(value) {
  return value.length * 2
}

function trimSessions(sessions) {
  let trimmed = sessions
  while (trimmed.length > MIN_SESSIONS_TO_KEEP) {
    const serialized = JSON.stringify(trimmed)
    if (approxBytes(serialized) <= TARGET_BYTES) return trimmed
    trimmed = trimmed.slice(0, trimmed.length - 1)
  }
  return trimmed
}

function persist(sessions) {
  let toWrite = sessions
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(toWrite))
    return toWrite
  } catch (err) {
    if (err?.name !== 'QuotaExceededError' && err?.code !== 22) {
      console.warn('Failed to persist sessions:', err)
      return toWrite
    }
    console.warn('localStorage quota exceeded; pruning oldest sessions.')
    toWrite = trimSessions(toWrite)
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(toWrite))
      return toWrite
    } catch (innerErr) {
      console.warn('Still over quota after pruning; clearing sessions.', innerErr)
      try {
        localStorage.removeItem(STORAGE_KEY)
      } catch {}
      return []
    }
  }
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
      return persist(next)
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

      return persist(next)
    })
  }, [])

  const deleteSession = useCallback((id) => {
    setSessions((prev) => {
      const next = prev.filter((session) => session.id !== id)
      return persist(next)
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
