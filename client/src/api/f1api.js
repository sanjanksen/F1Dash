// client/src/api/f1api.js
const BASE = '/api'
let circuitsPromise = null

async function apiFetch(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const fetchDriverStats = (name) => apiFetch(`/driver/${encodeURIComponent(name)}/stats`)
export const fetchCircuits = () => {
  if (!circuitsPromise) {
    circuitsPromise = apiFetch('/circuits').catch((error) => {
      circuitsPromise = null
      throw error
    })
  }
  return circuitsPromise
}
/**
 * Send a chat message and consume the SSE stream.
 * onDelta(text: string) is called with each accumulated text string as it arrives.
 * Resolves with { response: string, widgets: array } when the done event arrives.
 */
export async function sendChatMessage(message, history = [], onDelta = null) {
  const res = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, history }),
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let accumulated = ''
  let finalResponse = ''
  let finalWidgets = []

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() ?? ''

    for (const part of parts) {
      const trimmed = part.trim()
      if (!trimmed.startsWith('data: ')) continue
      let event
      try {
        event = JSON.parse(trimmed.slice(6))
      } catch {
        continue
      }

      if (event.type === 'delta') {
        accumulated += event.text
        if (onDelta) onDelta(accumulated)
      } else if (event.type === 'done') {
        finalResponse = event.text
        finalWidgets = event.widgets ?? []
      } else if (event.type === 'error') {
        throw new Error(event.detail || 'Unknown server error')
      }
    }
  }

  return { response: finalResponse, widgets: finalWidgets }
}
