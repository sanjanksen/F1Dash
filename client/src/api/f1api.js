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
export const sendChatMessage = (message, history = []) =>
  apiFetch('/chat', { method: 'POST', body: JSON.stringify({ message, history }) })
