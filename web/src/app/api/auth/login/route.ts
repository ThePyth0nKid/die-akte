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

  const res = await djangoFetch("/api/v1/auth/login/", {
    method: "POST",
    body: JSON.stringify({ login, password }),
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
