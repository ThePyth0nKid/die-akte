// @vitest-environment node
// E10: Einrichtung und Login nehmen nur JSON an und prüfen Sec-Fetch-Site/Origin, wenn vorhanden. Dieser Test schickt
// die echten Next-Routen gegen einen kleinen Server, der nur an 127.0.0.1 lauscht und mit dem Test endet, und prüft,
// was beim Backend ankommt.
import http from "node:http"
import type { AddressInfo } from "node:net"
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest"
import { NextRequest } from "next/server"

vi.mock("next/headers", () => ({ cookies: async () => ({ set: () => undefined }) }))

type Empfang = { methode: string; pfad: string; koepfe: http.IncomingHttpHeaders; rumpf: string }
const empfangen: Empfang[] = []
let server: http.Server
let einrichtung: typeof import("@/app/api/auth/einrichtung/route")
let login: typeof import("@/app/api/auth/login/route")

beforeAll(async () => {
  server = http.createServer((req, res) => {
    let rumpf = ""
    req.on("data", (d) => { rumpf += d })
    req.on("end", () => {
      empfangen.push({ methode: req.method ?? "", pfad: req.url ?? "", koepfe: req.headers, rumpf })
      res.setHeader("Content-Type", "application/json")
      if (req.url === "/api/v1/auth/einrichtung/" && req.method === "POST") {
        res.statusCode = 201
        res.end(JSON.stringify({ benutzername: "erika" }))
      } else if (req.url === "/api/v1/auth/login/") {
        res.end(JSON.stringify({ access: "a.b.c", refresh: "d.e.f" }))
      } else {
        res.end(JSON.stringify({ offen: true, grund: "offen" }))
      }
    })
  })
  await new Promise<void>((ok) => server.listen(0, "127.0.0.1", ok))
  process.env.DJANGO_API_URL = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
  vi.resetModules()
  einrichtung = await import("@/app/api/auth/einrichtung/route")
  login = await import("@/app/api/auth/login/route")
})

afterAll(async () => {
  await new Promise((ok) => server.close(ok))
  delete process.env.DJANGO_API_URL
})

// So kommt die Anfrage aus dem Browser bei der Next-Route an (gleiche Herkunft).
const ausDemBrowser = (pfad: string, daten: unknown) => new NextRequest(`http://localhost:8080${pfad}`, {
  method: "POST", body: JSON.stringify(daten),
  headers: { "Content-Type": "application/json", Origin: "http://localhost:8080", "Sec-Fetch-Site": "same-origin" },
})

function pruefeJsonOhneFremdeHerkunft(e: Empfang) {
  expect(e.koepfe["content-type"]).toBe("application/json")
  expect(() => JSON.parse(e.rumpf)).not.toThrow()
  // Server-zu-Server: kein Origin, und Sec-Fetch-Site höchstens „same-origin“ – das Backend lehnt also nicht ab.
  expect(e.koepfe.origin).toBeUndefined()
  expect([undefined, "same-origin", "none"]).toContain(e.koepfe["sec-fetch-site"])
}

describe("Next-Routen → Backend (E10)", () => {
  it("Einrichtung: Anlegen und Anmelden gehen als JSON ohne fremde Herkunft raus", async () => {
    empfangen.length = 0
    const res = await einrichtung.POST(ausDemBrowser("/api/auth/einrichtung",
      { code: "ABCDEF23", benutzername: "erika", passwort: "lang-genug-123", archiv_org: false }))
    expect(res.status).toBe(201)
    expect(empfangen.map((e) => e.pfad)).toEqual(["/api/v1/auth/einrichtung/", "/api/v1/auth/login/"])
    for (const e of empfangen) pruefeJsonOhneFremdeHerkunft(e)
    expect(JSON.parse(empfangen[0].rumpf)).toEqual({ code: "ABCDEF23", benutzername: "erika", passwort: "lang-genug-123", archiv_org: false })
  })

  it("Login geht als JSON ohne fremde Herkunft raus", async () => {
    empfangen.length = 0
    const res = await login.POST(ausDemBrowser("/api/auth/login", { login: "erika", password: "lang-genug-123" }))
    expect(res.status).toBe(200)
    expect(empfangen).toHaveLength(1)
    pruefeJsonOhneFremdeHerkunft(empfangen[0])
  })

  it("Einrichtung lesen (GET) braucht keinen Rumpf und trägt keine fremde Herkunft", async () => {
    empfangen.length = 0
    const res = await einrichtung.GET(new NextRequest("http://localhost:8080/api/auth/einrichtung"))
    expect(await res.json()).toEqual({ offen: true, grund: "offen" })
    expect(empfangen[0].methode).toBe("GET")
    expect(empfangen[0].koepfe.origin).toBeUndefined()
  })
})
