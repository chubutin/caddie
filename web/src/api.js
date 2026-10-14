const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export async function get(path) {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} en ${path}`)
  return res.json()
}

// Las distancias ya vienen en yardas desde la API (campos *_yd).
export const num = (v) => (v === null || v === undefined ? null : Number(v))
export const fmt = (v, d = 0) =>
  v === null || v === undefined ? '–' : Number(v).toFixed(d)
