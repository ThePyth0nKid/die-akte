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
})
