import { NextRequest, NextResponse } from "next/server"
import { cookies } from "next/headers"
import { DJANGO_API_URL } from "@/lib/server-api"
import { accessTokenCookie, refreshTokenCookie } from "@/lib/cookie-config"
import { gleicheHerkunft } from "@/lib/herkunft"

const FREMD = { detail: "Anfrage von fremder Herkunft abgelehnt." }

async function proxyRequest(request: NextRequest) {
  if (!gleicheHerkunft(request.method, (n) => request.headers.get(n))) {
    return NextResponse.json(FREMD, { status: 403 })
  }
  const cookieStore = await cookies()
  const accessToken = cookieStore.get("access_token")?.value

  if (!accessToken) {
    return NextResponse.json({ error: "Not authenticated" }, { status: 401 })
  }

  const url = new URL(request.url)
  let proxyPath = url.pathname.replace("/api/proxy", "")
  // Django requires trailing slash on all endpoints
  if (!proxyPath.endsWith("/")) {
    proxyPath += "/"
  }
  const targetUrl = `${DJANGO_API_URL}${proxyPath}${url.search}`

  const headers: Record<string, string> = {
    Authorization: `Bearer ${accessToken}`,
  }

  const contentType = request.headers.get("content-type")
  if (contentType) {
    headers["Content-Type"] = contentType
  }

  const isMultipart = contentType?.includes("multipart/form-data")
  const body =
    request.method !== "GET" && request.method !== "HEAD"
      ? isMultipart
        ? Buffer.from(await request.arrayBuffer())
        : await request.text()
      : undefined

  const res = await fetch(targetUrl, {
    method: request.method,
    headers,
    body,
  })

  if (res.status === 401) {
    const refreshToken = cookieStore.get("refresh_token")?.value
    if (!refreshToken) {
      return NextResponse.json({ error: "Session expired" }, { status: 401 })
    }

    const refreshRes = await fetch(`${DJANGO_API_URL}/api/v1/auth/jwt/refresh/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh: refreshToken }),
    })

    if (!refreshRes.ok) {
      // Cookies nicht löschen: Laufen mehrere Anfragen gleichzeitig ab, erneuert die erste, und die übrigen
      // scheitern am schon verbrauchten Refresh-Token (Rotation mit Sperrliste). Löschten sie die Cookies, wäre
      // die frische Sitzung der ersten gleich wieder weg. Der Browser versucht es mit den neuen Cookies erneut.
      return NextResponse.json({ error: "Session expired" }, { status: 401 })
    }

    const { access, refresh } = await refreshRes.json()

    cookieStore.set(accessTokenCookie(access))

    if (refresh) {
      cookieStore.set(refreshTokenCookie(refresh))
    }

    headers["Authorization"] = `Bearer ${access}`
    const retryRes = await fetch(targetUrl, {
      method: request.method,
      headers,
      body,
    })

    if (retryRes.status === 204) {
      return new NextResponse(null, { status: 204 })
    }

    return new NextResponse(await retryRes.arrayBuffer(), {
      status: retryRes.status,
      headers: antwortKoepfe(retryRes),
    })
  }

  // 204 No Content — return empty response without body
  if (res.status === 204) {
    return new NextResponse(null, { status: 204 })
  }

  // Als Bytes, nicht als Text: sonst zerbricht jede Datei-Antwort (z. B. der
  // Obsidian-Export der Akte als ZIP) an der UTF-8-Dekodierung.
  return new NextResponse(await res.arrayBuffer(), {
    status: res.status,
    headers: antwortKoepfe(res),
  })
}

function antwortKoepfe(res: Response): Record<string, string> {
  const koepfe: Record<string, string> = {
    "Content-Type": res.headers.get("Content-Type") || "application/json",
  }
  // Schutz-Köpfe des Backends mitgeben: Dateien fremder Herkunft (Beweiskopien der Akte)
  // laufen über unsere eigene Domain und sollen dort nicht als Seite ausgeführt werden.
  for (const name of ["Content-Disposition", "Content-Security-Policy", "X-Content-Type-Options", "Cache-Control"]) {
    const wert = res.headers.get(name)
    if (wert) koepfe[name] = wert
  }
  return koepfe
}

export const GET = proxyRequest
export const POST = proxyRequest
export const PUT = proxyRequest
export const PATCH = proxyRequest
export const DELETE = proxyRequest
