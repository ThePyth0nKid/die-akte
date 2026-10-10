// Anfragen der angemeldeten Redaktion laufen über den Proxy der Web-Oberfläche (/api/proxy), der das JWT aus dem
// httpOnly-Cookie anhängt. Bei 401 wird einmal erneuert, dann neu versucht – auch wenn das Erneuern scheitert: Laufen
// zwei Anfragen gleichzeitig ab, verbraucht die erste den Refresh-Token (Rotation mit Sperrliste), und die zweite
// kommt mit den frisch gesetzten Cookies der ersten durch.

const warten = (ms: number) => new Promise((ok) => setTimeout(ok, ms))

export async function authFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const isFormData = init.body instanceof FormData
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string>),
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
  }

  const res = await fetch(`/api/proxy${input}`, { ...init, headers, credentials: "include" })
  if (res.status !== 401) return res

  const refresh = await fetch("/api/auth/refresh", { method: "POST", credentials: "include" })
  if (!refresh.ok) await warten(300)
  const nochmal = await fetch(`/api/proxy${input}`, { ...init, headers, credentials: "include" })
  if (nochmal.status === 401 && !refresh.ok) throw new Error("Session expired")
  return nochmal
}
