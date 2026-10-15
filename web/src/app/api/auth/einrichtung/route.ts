import { NextRequest, NextResponse } from "next/server"
import { cookies } from "next/headers"
import { djangoFetch } from "@/lib/server-api"
import { accessTokenCookie, refreshTokenCookie } from "@/lib/cookie-config"
import { gleicheHerkunft } from "@/lib/herkunft"

// Erstes Konto im Browser (ersetzt die Passwortfrage im Terminal). GET fragt, ob die Einrichtung offen ist; POST legt
// das Konto beim Backend an und meldet danach direkt an (wie /api/auth/login), damit der Mensch gleich auf der Akte
// landet. Fehlertexte kommen deutsch vom Backend und werden unverändert weitergereicht.

// Der Zustand ändert sich mit dem ersten Konto: nie beim Bauen vorberechnen, nie zwischenspeichern.
export const dynamic = "force-dynamic"

const NICHT_SPEICHERN = { "Cache-Control": "no-store" }
const NICHT_ERREICHBAR = { fehler: "Die Ultra-Akte ist gerade nicht erreichbar. Läuft sie noch? Sonst neu starten (START-AKTE)." }

export async function GET(request: NextRequest) {
  // Die Besucher-IP weitergeben wie beim Anlegen und beim Login (Drossel je Absender im Backend).
  const absender = request.headers.get("x-forwarded-for")
  try {
    const res = await djangoFetch("/api/v1/auth/einrichtung/", {
      method: "GET", cache: "no-store", headers: absender ? { "X-Forwarded-For": absender } : {},
    })
    const daten = (await res.json().catch(() => ({}))) as { offen?: unknown; grund?: unknown }
    // `grund` (offen | kein_code | eingerichtet) gibt es seit 0.2.0; nur bekannte Werte gehen weiter.
    const grund = ["offen", "kein_code", "eingerichtet"].includes(String(daten.grund)) ? String(daten.grund) : undefined
    return NextResponse.json({ offen: res.ok && daten.offen === true, ...(res.ok && grund ? { grund } : {}) },
      { status: res.ok ? 200 : res.status, headers: NICHT_SPEICHERN })
  } catch {
    return NextResponse.json({ offen: false, ...NICHT_ERREICHBAR }, { status: 502, headers: NICHT_SPEICHERN })
  }
}

export async function POST(request: NextRequest) {
  if (!gleicheHerkunft(request.method, (n) => request.headers.get(n))) {
    return NextResponse.json({ fehler: "Anfrage von fremder Herkunft abgelehnt." }, { status: 403 })
  }
  const body = (await request.json().catch(() => null)) as Record<string, unknown> | null
  const { code, benutzername, passwort, archiv_org: archivOrg } = body ?? {}
  if (typeof code !== "string" || typeof benutzername !== "string" || typeof passwort !== "string"
    || typeof archivOrg !== "boolean" || !code || !benutzername.trim() || !passwort) {
    return NextResponse.json({ fehler: "Bitte alle Felder ausfüllen." }, { status: 400 })
  }

  // Die Besucher-IP, die der vorgeschaltete Proxy (Caddy) gesetzt hat: Das Backend drosselt damit wie beim Login.
  const absender = request.headers.get("x-forwarded-for")
  const koepfe: Record<string, string> = absender ? { "X-Forwarded-For": absender } : {}
  let res: Response
  try {
    res = await djangoFetch("/api/v1/auth/einrichtung/", {
      method: "POST",
      body: JSON.stringify({ code, benutzername: benutzername.trim(), passwort, archiv_org: archivOrg }),
      headers: koepfe,
    })
  } catch {
    return NextResponse.json(NICHT_ERREICHBAR, { status: 502 })
  }
  const daten = (await res.json().catch(() => ({}))) as Record<string, unknown>
  if (res.status !== 201) return NextResponse.json(daten, { status: res.status })

  // Gleich anmelden. Scheitert das (etwa an der Drossel), ist das Konto trotzdem da: dann zum Login.
  const name = typeof daten.benutzername === "string" && daten.benutzername ? daten.benutzername : benutzername.trim()
  try {
    const login = await djangoFetch("/api/v1/auth/login/", {
      method: "POST",
      body: JSON.stringify({ login: name, password: passwort }),
      headers: koepfe,
    })
    if (login.ok) {
      const { access, refresh } = (await login.json()) as { access: string; refresh: string }
      const cookieStore = await cookies()
      cookieStore.set(accessTokenCookie(access))
      cookieStore.set(refreshTokenCookie(refresh))
      return NextResponse.json({ angelegt: true, angemeldet: true, benutzername: name, ziel: "/akte" }, { status: 201 })
    }
  } catch {
    // Konto steht; die Anmeldung holt der Mensch im Login nach.
  }
  return NextResponse.json({ angelegt: true, angemeldet: false, benutzername: name, ziel: "/login" }, { status: 201 })
}
