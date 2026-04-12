// client/src/api/f1api.js
const BASE = '/api'

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

export const fetchDrivers = () => apiFetch('/drivers')
export const fetchDriverStats = (name) => apiFetch(`/driver/${encodeURIComponent(name)}/stats`)
export const fetchCircuits = () => apiFetch('/circuits')
export const sendChatMessage = (message) =>
  apiFetch('/chat', { method: 'POST', body: JSON.stringify({ message }) })
