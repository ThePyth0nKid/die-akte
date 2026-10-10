import { describe, expect, it } from "vitest"
import { NextRequest } from "next/server"
import { AKTE_OFFEN, proxy as middleware } from "@/proxy"

function anfrage(pfad: string, angemeldet = false) {
  const req = new NextRequest(new URL(pfad, "http://localhost:8080"))
  if (angemeldet) req.cookies.set("access_token", "x")
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
})
