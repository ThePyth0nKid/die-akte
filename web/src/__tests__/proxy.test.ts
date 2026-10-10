import { describe, expect, it } from "vitest"
import { NextRequest } from "next/server"
import { AKTE_OFFEN, proxy as middleware } from "@/proxy"

function jwt(expSekunden: number) {
  const teil = (o: object) => btoa(JSON.stringify(o)).replace(/=+$/, "")
  return `${teil({ alg: "HS256" })}.${teil({ exp: Math.floor(Date.now() / 1000) + expSekunden })}.sig`
}

function anfrage(pfad: string, angemeldet = false, token = jwt(600)) {
  const req = new NextRequest(new URL(pfad, "http://localhost:8080"))
  if (angemeldet) req.cookies.set("access_token", token)
  return middleware(req)
}

describe("middleware", () => {
  it("lässt Übersicht und Wand ohne Konto durch", () => {
    expect(AKTE_OFFEN.test("/akte")).toBe(true)
    expect(AKTE_OFFEN.test("/akte/demo-musterhafen")).toBe(true)
    expect(anfrage("/akte/demo").headers.get("location")).toBeNull()
  })
  it("schickt die Aufnahme ohne Konto zum Login", () => {
    const antwort = anfrage("/akte/demo/render")
    expect(antwort.headers.get("location")).toContain("/login?redirect=%2Fakte%2Fdemo%2Frender")
  })
  it("lässt die Aufnahme mit Konto durch", () => {
    expect(anfrage("/akte/demo/render", true).headers.get("location")).toBeNull()
  })
  it("leitet Angemeldete vom Login zur Akte", () => {
    expect(anfrage("/login", true).headers.get("location")).toContain("/akte")
  })
  it("zeigt den Login, wenn das Access-Token abgelaufen oder kaputt ist", () => {
    expect(anfrage("/login", true, jwt(-60)).headers.get("location")).toBeNull()
    expect(anfrage("/login", true, "kein-jwt").headers.get("location")).toBeNull()
  })
})
