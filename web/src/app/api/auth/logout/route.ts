import { NextRequest, NextResponse } from "next/server"
import { cookies } from "next/headers"
import { djangoFetch } from "@/lib/server-api"
import { gleicheHerkunft } from "@/lib/herkunft"

// Abmelden: Der Refresh-Token kommt beim Backend auf die Sperrliste (gilt nie wieder, auch nicht aus einer Kopie),
// danach werden die Cookies gelöscht. Scheitert das Backend, wird trotzdem lokal abgemeldet.
export async function POST(request: NextRequest) {
  if (!gleicheHerkunft(request.method, (n) => request.headers.get(n))) {
    return NextResponse.json({ detail: "Anfrage von fremder Herkunft abgelehnt." }, { status: 403 })
  }
  const cookieStore = await cookies()
  const refresh = cookieStore.get("refresh_token")?.value
  if (refresh) {
    await djangoFetch("/api/v1/auth/logout/", { method: "POST", body: JSON.stringify({ refresh }) }).catch(() => null)
  }
  const domain = process.env.COOKIE_DOMAIN || undefined
  cookieStore.delete({ name: "access_token", domain, path: "/" })
  cookieStore.delete({ name: "refresh_token", domain, path: "/" })
  return NextResponse.json({ success: true })
}
