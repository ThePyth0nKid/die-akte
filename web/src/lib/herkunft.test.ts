import { describe, expect, it } from "vitest"
import { gleicheHerkunft } from "./herkunft"

const koepfe = (k: Record<string, string>) => (name: string) => k[name] ?? null

describe("gleicheHerkunft", () => {
  it("lässt Lesen immer durch", () => {
    expect(gleicheHerkunft("GET", koepfe({ "sec-fetch-site": "cross-site" }))).toBe(true)
  })
  it("verweigert ändernde Anfragen fremder Seiten", () => {
    expect(gleicheHerkunft("POST", koepfe({ "sec-fetch-site": "cross-site" }))).toBe(false)
    expect(gleicheHerkunft("DELETE", koepfe({ "sec-fetch-site": "same-site" }))).toBe(false)
    expect(gleicheHerkunft("POST", koepfe({ origin: "https://boese.example", host: "localhost:8080" }))).toBe(false)
    expect(gleicheHerkunft("POST", koepfe({ origin: "null", host: "localhost:8080" }))).toBe(false)
  })
  it("lässt die eigene Oberfläche durch", () => {
    expect(gleicheHerkunft("POST", koepfe({ "sec-fetch-site": "same-origin" }))).toBe(true)
    expect(gleicheHerkunft("PATCH", koepfe({ origin: "http://localhost:8080", host: "localhost:8080" }))).toBe(true)
  })
  it("lässt Anfragen ohne Browser-Köpfe durch (curl, Server)", () => {
    expect(gleicheHerkunft("POST", koepfe({ host: "localhost:8080" }))).toBe(true)
  })
})
