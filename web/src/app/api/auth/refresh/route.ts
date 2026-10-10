import { NextRequest, NextResponse } from "next/server"
import { cookies } from "next/headers"
import { djangoFetch } from "@/lib/server-api"
import { accessTokenCookie, refreshTokenCookie } from "@/lib/cookie-config"
import { gleicheHerkunft } from "@/lib/herkunft"

export async function POST(request: NextRequest) {
  if (!gleicheHerkunft(request.method, (n) => request.headers.get(n))) {
    return NextResponse.json({ detail: "Anfrage von fremder Herkunft abgelehnt." }, { status: 403 })
  }
  const cookieStore = await cookies()
  const refreshToken = cookieStore.get("refresh_token")?.value

  if (!refreshToken) {
    return NextResponse.json({ error: "No refresh token" }, { status: 401 })
  }

  const res = await djangoFetch("/api/v1/auth/jwt/refresh/", {
    method: "POST",
    body: JSON.stringify({ refresh: refreshToken }),
  })

  if (!res.ok) {
    // Cookies bleiben (siehe Proxy): Eine parallele Erneuerung kann gerade frische gesetzt haben.
    return NextResponse.json({ error: "Refresh failed" }, { status: 401 })
  }

  const { access, refresh } = await res.json()

  cookieStore.set(accessTokenCookie(access))

  if (refresh) {
    cookieStore.set(refreshTokenCookie(refresh))
  }

  return NextResponse.json({ success: true })
}
