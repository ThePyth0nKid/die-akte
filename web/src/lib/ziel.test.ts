import { describe, expect, it } from "vitest"
import { sicheresZiel } from "./ziel"

describe("sicheresZiel", () => {
  it("lässt interne Pfade durch", () => {
    expect(sicheresZiel("/akte/demo")).toBe("/akte/demo")
  })
  it("fällt bei fehlendem Ziel auf /akte zurück", () => {
    expect(sicheresZiel(null)).toBe("/akte")
    expect(sicheresZiel("")).toBe("/akte")
  })
  it("verweigert fremde Ziele", () => {
    expect(sicheresZiel("https://boese.example")).toBe("/akte")
    expect(sicheresZiel("//boese.example")).toBe("/akte")
    expect(sicheresZiel("/\\boese.example")).toBe("/akte")
  })
  it("verweigert Steuerzeichen, die der Browser entfernt (aus /<Tab>/x wird //x)", () => {
    for (const z of ["/\t/boese.example", "/\n/boese.example", "/\r\n/boese.example", "/\u0000/x", "/a\\b"]) {
      expect(sicheresZiel(z)).toBe("/akte")
    }
  })
  it("behält Suche und Anker interner Ziele", () => {
    expect(sicheresZiel("/akte/demo?karte=senat#k1")).toBe("/akte/demo?karte=senat#k1")
    expect(sicheresZiel("/akte/../login")).toBe("/login")
  })
})
