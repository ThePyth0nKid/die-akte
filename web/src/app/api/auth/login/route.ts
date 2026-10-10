import { NextRequest, NextResponse } from "next/server"
import { cookies } from "next/headers"
import { djangoFetch } from "@/lib/server-api"
import { accessTokenCookie, refreshTokenCookie } from "@/lib/cookie-config"
import { gleicheHerkunft } from "@/lib/herkunft"

export async function POST(request: NextRequest) {
  if (!gleicheHerkunft(request.method, (n) => request.headers.get(n))) {
    return NextResponse.json({ detail: "Anfrage von fremder Herkunft abgelehnt." }, { status: 403 })
  }
  const body = await request.json()
  const { login, password } = body

  if (!login || !password) {
    return NextResponse.json(
      { detail: "Login and password are required" },
      { status: 400 }
    )
  }

  // Die Besucher-IP, die der vorgeschaltete Proxy (Caddy) gesetzt hat, an das Backend weitergeben: Dort bremst sie
  // Fehlversuche je Konto und Absender (wirksam nur mit AKTE_VERTRAUTE_PROXYS).
  const absender = request.headers.get("x-forwarded-for")
  const res = await djangoFetch("/api/v1/auth/login/", {
    method: "POST",
    body: JSON.stringify({ login, password }),
    headers: absender ? { "X-Forwarded-For": absender } : {},
  })

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: "Invalid credentials" }))
    return NextResponse.json(errorData, { status: res.status })
  }

  const { access, refresh } = await res.json()

  const cookieStore = await cookies()
  cookieStore.set(accessTokenCookie(access))
  cookieStore.set(refreshTokenCookie(refresh))

  return NextResponse.json({ success: true })
}
