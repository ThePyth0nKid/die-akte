// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { NextRequest } from "next/server"

// Die Route meldet nach dem Anlegen direkt an (wie /api/auth/login): Cookies landen im Cookie-Speicher von Next.
const gesetzt: { name: string; value: string }[] = []
vi.mock("next/headers", () => ({
  cookies: async () => ({ set: (c: { name: string; value: string }) => { gesetzt.push(c) } }),
}))

const { GET, POST } = await import("@/app/api/auth/einrichtung/route")

const antwort = (status: number, daten: unknown) =>
  new Response(JSON.stringify(daten), { status, headers: { "Content-Type": "application/json" } })

function anfrage(daten: unknown, koepfe: Record<string, string> = {}) {
  return new NextRequest("http://localhost:8080/api/auth/einrichtung", {
    method: "POST", body: JSON.stringify(daten), headers: { "Content-Type": "application/json", ...koepfe },
  })
}

const GUT = { code: "ABCDEF23", benutzername: "erika", passwort: "lang-genug-123", archiv_org: false }

const lesen = (koepfe: Record<string, string> = {}) =>
  new NextRequest("http://localhost:8080/api/auth/einrichtung", { headers: koepfe })

describe("/api/auth/einrichtung", () => {
  const holen = vi.fn<typeof fetch>()
  beforeEach(() => { gesetzt.length = 0; holen.mockReset(); vi.stubGlobal("fetch", holen) })
  afterEach(() => { vi.unstubAllGlobals() })

  it("GET reicht „offen“ durch und speichert nichts zwischen", async () => {
    holen.mockResolvedValueOnce(antwort(200, { offen: true }))
    const res = await GET(lesen())
    expect(await res.json()).toEqual({ offen: true })
    expect(res.headers.get("cache-control")).toBe("no-store")
    expect(String(holen.mock.calls[0][0])).toMatch(/\/api\/v1\/auth\/einrichtung\/$/)
  })

  it("GET reicht den Grund durch, aber nur bekannte Werte", async () => {
    holen.mockResolvedValueOnce(antwort(200, { offen: false, grund: "kein_code" }))
    expect(await (await GET(lesen())).json()).toEqual({ offen: false, grund: "kein_code" })
    holen.mockResolvedValueOnce(antwort(200, { offen: false, grund: "<script>" }))
    expect(await (await GET(lesen())).json()).toEqual({ offen: false })
  })

  it("GET reicht die Besucher-IP weiter wie Login und Anlegen (CR-12)", async () => {
    holen.mockResolvedValueOnce(antwort(200, { offen: true, grund: "offen" }))
    await GET(lesen({ "x-forwarded-for": "198.51.100.9" }))
    expect((holen.mock.calls[0][1]?.headers as Record<string, string>)["X-Forwarded-For"]).toBe("198.51.100.9")
  })

  it("GET meldet eine nicht erreichbare Akte mit 502", async () => {
    holen.mockRejectedValueOnce(new TypeError("fetch failed"))
    const res = await GET(lesen())
    expect(res.status).toBe(502)
    expect((await res.json()).offen).toBe(false)
  })

  it("POST legt an, meldet direkt an und setzt beide Cookies", async () => {
    holen
      .mockResolvedValueOnce(antwort(201, { benutzername: "erika" }))
      .mockResolvedValueOnce(antwort(200, { access: "a.b.c", refresh: "d.e.f" }))
    const res = await POST(anfrage(GUT, { "x-forwarded-for": "203.0.113.7" }))
    expect(res.status).toBe(201)
    expect(await res.json()).toMatchObject({ angelegt: true, angemeldet: true, ziel: "/akte" })
    expect(gesetzt.map((c) => c.name)).toEqual(["access_token", "refresh_token"])
    const [einrichtung, login] = holen.mock.calls
    expect(JSON.parse(String(einrichtung[1]?.body))).toEqual(GUT)
    expect(JSON.parse(String(login[1]?.body))).toEqual({ login: "erika", password: "lang-genug-123" })
    expect((einrichtung[1]?.headers as Record<string, string>)["X-Forwarded-For"]).toBe("203.0.113.7")
  })

  it("POST: Konto angelegt, Anmeldung scheitert → zum Login", async () => {
    holen
      .mockResolvedValueOnce(antwort(201, { benutzername: "erika" }))
      .mockResolvedValueOnce(antwort(429, { detail: "throttled" }))
    const res = await POST(anfrage(GUT))
    expect(res.status).toBe(201)
    expect(await res.json()).toMatchObject({ angelegt: true, angemeldet: false, ziel: "/login" })
    expect(gesetzt).toEqual([])
  })

  it("POST reicht deutsche Fehler des Backends unverändert durch", async () => {
    holen.mockResolvedValueOnce(antwort(403, { fehler: "Einrichtungscode stimmt nicht." }))
    const res = await POST(anfrage(GUT))
    expect(res.status).toBe(403)
    expect(await res.json()).toEqual({ fehler: "Einrichtungscode stimmt nicht." })
    expect(holen).toHaveBeenCalledTimes(1)
  })

  it("POST lehnt fremde Herkunft und unvollständige Angaben ab, ohne das Backend zu fragen", async () => {
    expect((await POST(anfrage(GUT, { "sec-fetch-site": "cross-site" }))).status).toBe(403)
    expect((await POST(anfrage({ ...GUT, archiv_org: "nein" }))).status).toBe(400)
    expect((await POST(anfrage({ ...GUT, passwort: "" }))).status).toBe(400)
    expect(holen).not.toHaveBeenCalled()
  })
})
