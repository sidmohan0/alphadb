export interface ApiEnvelope<T> {
  ok: boolean
  data?: T
  error?: {
    code: string
    message: string
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  return apiRequest<T>(path, { method: "GET" })
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  return apiRequest<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
}

async function apiRequest<T>(path: string, init: RequestInit): Promise<T> {
  const normalized = path.startsWith("/") ? path : `/${path}`
  const response = await fetch(`/api/alphadb${normalized}`, {
    ...init,
    cache: "no-store",
  })
  const payload = await response.json()
  if (payload && typeof payload === "object" && "ok" in payload) {
    const envelope = payload as ApiEnvelope<T>
    if (!response.ok || !envelope.ok) {
      throw new Error(envelope.error?.message || "AlphaDB API request failed")
    }
    return envelope.data as T
  }
  if (!response.ok) {
    throw new Error("AlphaDB API request failed")
  }
  return payload as T
}
