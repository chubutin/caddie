const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export async function get(path) {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} en ${path}`)
  return res.json()
}

export async function post(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `${res.status} ${res.statusText}`)
  return data
}

export async function put(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `${res.status} ${res.statusText}`)
  return data
}

export async function del(path) {
  const res = await fetch(`${BASE}${path}`, { method: 'DELETE' })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `${res.status} ${res.statusText}`)
  return data
}

// Las distancias ya vienen en yardas desde la API (campos *_yd).
export const num = (v) => (v === null || v === undefined ? null : Number(v))
export const fmt = (v, d = 0) =>
  v === null || v === undefined ? '–' : Number(v).toFixed(d)
