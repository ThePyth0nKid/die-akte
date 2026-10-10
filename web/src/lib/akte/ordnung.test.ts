// @vitest-environment node
import { describe, expect, it } from "vitest"
import { bildArt, etikettenVersatz, freierPlatz, trifft } from "./ordnung"

describe("freierPlatz", () => {
  it("bleibt, wo nichts liegt", () => {
    expect(freierPlatz({ x: 0, y: 0, b: 220, h: 380 }, [{ x: 1000, y: 0, b: 220, h: 380 }])).toEqual({ x: 0, y: 0 })
  })

  it("rutscht von einer anderen Karte herunter", () => {
    const andere = [{ x: 0, y: 0, b: 220, h: 380 }]
    const p = freierPlatz({ x: 40, y: 40, b: 220, h: 380 }, andere)
    expect(trifft({ x: p.x, y: p.y, b: 220, h: 380 }, andere[0], 30)).toBe(false)
  })
})

describe("etikettenVersatz", () => {
  it("schiebt übereinanderliegende Etiketten auseinander", () => {
    const v = etikettenVersatz([
      { id: "a", x: 100, y: 100, b: 120, h: 22 },
      { id: "b", x: 110, y: 104, b: 120, h: 22 },
      { id: "c", x: 900, y: 100, b: 120, h: 22 },
    ])
    expect(v.get("a")).toBe(0)
    expect(v.get("b")).not.toBe(0)
    expect(v.get("c")).toBe(0)
  })
})

describe("etikettenVersatz mit Karten", () => {
  it("rutscht unter eine Karte, statt sie zu verdecken", () => {
    const karte = { x: 0, y: 0, b: 220, h: 300 }
    const v = etikettenVersatz([{ id: "a", x: 100, y: 50, b: 120, h: 22 }], 4, [karte])
    const r = { x: 40, y: 50 - 11 + (v.get("a") ?? 0), b: 120, h: 22 }
    expect(trifft(r, karte, 4)).toBe(false)
  })
})

describe("bildArt", () => {
  it("zeigt Logos, Siegel und Wappen ganz", () => {
    expect(bildArt("Logo: Microsoft Corporation, Public domain, Wikimedia Commons")).toBe("zeichen")
    expect(bildArt("Siegel: ICE, Public domain, Wikimedia Commons")).toBe("zeichen")
    expect(bildArt("Wappen: Land Musterhafen, Public domain, Wikimedia Commons")).toBe("zeichen")
  })

  it("lässt CC BY-SA unbeschnitten und füllt sonst", () => {
    expect(bildArt("Foto: Gage Skidmore, CC BY-SA 3.0, Wikimedia Commons")).toBe("unbeschnitten")
    expect(bildArt("Foto: UK Government, CC BY 2.0, Wikimedia Commons")).toBe("fuellend")
    expect(bildArt("")).toBe("fuellend")
  })
})
