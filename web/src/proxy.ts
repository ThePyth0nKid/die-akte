import { NextResponse } from "next/server"
import type { NextRequest } from "next/server"

// Ohne Anmeldung erreichbar: Startseite, Login, die API-Routen der Oberfläche, die Board-Übersicht und die Wand eines
// Boards. Welche Boards wirklich ohne Konto lesbar sind, entscheidet das Backend (Board.oeffentlich +
// AKTE_OEFFENTLICH_AKTIV). Tiefere Pfade wie /akte/<slug>/render brauchen ein Konto.
export const AKTE_OFFEN = /^\/akte(\/[a-z0-9][a-z0-9-]*)?\/?$/
const OFFEN = ["/", "/login", "/api"]

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl
  const angemeldet = Boolean(request.cookies.get("access_token")?.value)

  if (pathname === "/login" && angemeldet) {
    return NextResponse.redirect(new URL("/akte", request.url))
  }
  const offen = OFFEN.some((p) => (p === "/" ? pathname === "/" : pathname === p || pathname.startsWith(p + "/")))
  if (offen || AKTE_OFFEN.test(pathname)) return NextResponse.next()

  if (!angemeldet) {
    const ziel = new URL("/login", request.url)
    ziel.searchParams.set("redirect", pathname)
    return NextResponse.redirect(ziel)
  }
  return NextResponse.next()
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\..*).*)"],
}
