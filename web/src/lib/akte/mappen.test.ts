// @vitest-environment node
import { describe, expect, it } from "vitest"
import { buendelBreite, buendelText, eintauchKamera, mappenAdresse, pfadLesen, zurueckAdresse } from "./mappen"

describe("pfadLesen", () => {
  it("liest den Weg aus ?von= und verwirft Unsinn", () => {
    expect(pfadLesen("hauptwand,bfm", [], "nordlicht")).toEqual(["hauptwand", "bfm"])
    expect(pfadLesen("hauptwand,<script>,,bfm", [], "x")).toEqual(["hauptwand", "bfm"])
    // Die aktuelle Wand steht nie im eigenen Weg (kein Kreis in den Brotkrumen).
    expect(pfadLesen("hauptwand,nordlicht", [], "nordlicht")).toEqual(["hauptwand"])
  })
  it("nimmt ohne Angabe die erste Eltern-Wand", () => {
    expect(pfadLesen(null, [{ slug: "hauptwand", titel: "Die Hauptwand" }])).toEqual(["hauptwand"])
    expect(pfadLesen("", [])).toEqual([])
  })
})

describe("Adressen", () => {
  it("baut die Adresse einer Mappe aus dem Weg", () => {
    expect(mappenAdresse("bfm", ["hauptwand"], "musk")).toBe("/akte/bfm?von=hauptwand,musk")
    expect(mappenAdresse("bfm", [], "hauptwand")).toBe("/akte/bfm?von=hauptwand")
  })
  it("geht eine Ebene zurück und merkt sich, woher", () => {
    expect(zurueckAdresse(["hauptwand", "bfm"], "nordlicht")).toBe("/akte/bfm?von=hauptwand&aus=nordlicht")
    expect(zurueckAdresse(["hauptwand"], "bfm")).toBe("/akte/hauptwand?aus=bfm")
    expect(zurueckAdresse([], "hauptwand")).toBeNull()
  })
})

describe("Bündel", () => {
  it("wird mit mehr Fäden dicker, aber nicht beliebig", () => {
    expect(buendelBreite(1)).toBe(3)
    expect(buendelBreite(8)).toBeGreaterThan(buendelBreite(2))
    expect(buendelBreite(10_000)).toBe(12)
  })
  it("schreibt Zahl und Arten", () => {
    expect(buendelText({ faeden: [1], je_typ: [["amt", 1]] })).toEqual({ zahl: "1 Faden", typen: "Amt 1" })
    expect(buendelText({ faeden: [1, 2, 3], je_typ: [["finanzierung", 2], ["amt", 1]] }).zahl).toBe("3 Fäden")
    expect(buendelText({ faeden: [1, 2, 3], je_typ: [["finanzierung", 2], ["amt", 1]] }).typen).toBe("Finanzierung 2 · Amt 1")
  })
})

describe("eintauchKamera", () => {
  it("füllt den Schirm mit dem Rechteck", () => {
    const k = eintauchKamera({ x: 100, y: 200, b: 560, h: 380 }, { b: 1120, h: 1140 })
    expect(k.x).toBe(380)
    expect(k.y).toBe(390)
    expect(k.zoom).toBe(2)
    expect(eintauchKamera({ x: 0, y: 0, b: 10, h: 10 }, { b: 1000, h: 1000 }).zoom).toBe(3)
  })
})
