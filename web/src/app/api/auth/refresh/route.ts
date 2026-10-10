import { NextResponse } from "next/server"
import { cookies } from "next/headers"
import { djangoFetch } from "@/lib/server-api"
import { accessTokenCookie, refreshTokenCookie } from "@/lib/cookie-config"

export async function POST() {
  const cookieStore = await cookies()
  const cookieDomain = process.env.COOKIE_DOMAIN || undefined
  const refreshToken = cookieStore.get("refresh_token")?.value

  if (!refreshToken) {
    return NextResponse.json({ error: "No refresh token" }, { status: 401 })
  }

  const res = await djangoFetch("/api/v1/auth/jwt/refresh/", {
    method: "POST",
    body: JSON.stringify({ refresh: refreshToken }),
  })

  if (!res.ok) {
    cookieStore.delete({ name: "access_token", domain: cookieDomain, path: "/" })
    cookieStore.delete({ name: "refresh_token", domain: cookieDomain, path: "/" })
    return NextResponse.json({ error: "Refresh failed" }, { status: 401 })
  }

  const { access, refresh } = await res.json()

  cookieStore.set(accessTokenCookie(access))

  if (refresh) {
    cookieStore.set(refreshTokenCookie(refresh))
  }

  return NextResponse.json({ success: true })
}
