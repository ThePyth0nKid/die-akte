// Anfragen der angemeldeten Redaktion laufen über den Proxy der Web-Oberfläche (/api/proxy), der das JWT aus dem
// httpOnly-Cookie anhängt. Bei 401 wird einmal erneuert, dann neu versucht.

export async function authFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const isFormData = init.body instanceof FormData
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string>),
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
  }

  const res = await fetch(`/api/proxy${input}`, { ...init, headers, credentials: "include" })
  if (res.status !== 401) return res

  const refresh = await fetch("/api/auth/refresh", { method: "POST", credentials: "include" })
  if (!refresh.ok) throw new Error("Session expired")
  return fetch(`/api/proxy${input}`, { ...init, headers, credentials: "include" })
}
