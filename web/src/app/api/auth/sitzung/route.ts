import { NextResponse } from "next/server"
import { cookies } from "next/headers"
import { laeuftNoch } from "@/lib/jwt"

// Ist hier jemand angemeldet? Die Cookies sind httpOnly, der Browser kann sie nicht selbst lesen. Ob das Konto zur
// Redaktion gehört, entscheidet weiterhin das Backend; hier geht es nur um „Anmelden“ oder „Abmelden“.
export async function GET() {
  const cookieStore = await cookies()
  const angemeldet = laeuftNoch(cookieStore.get("access_token")?.value) || Boolean(cookieStore.get("refresh_token")?.value)
  return NextResponse.json({ angemeldet }, { headers: { "Cache-Control": "no-store" } })
}
