import { describe, expect, it } from "vitest"
import { AkteFehler } from "./api"
import {
  b64url, b64urlLesen, begruendungsFrage, HINWEIS_VEROEFFENTLICHUNG, ketteVeraendert, zusammenfassung, type Vorbereitung,
} from "./unterschrift"

describe("b64url", () => {
  it("hin und zurück ohne Auffüllung", () => {
    const roh = new Uint8Array([0, 1, 2, 250, 251, 252, 253, 254, 255])
    const text = b64url(roh)
    expect(text).not.toContain("=")
    expect(text).not.toMatch(/[+/]/)
    expect(Array.from(b64urlLesen(text))).toEqual(Array.from(roh))
  })
})

describe("zusammenfassung", () => {
  it("zeigt Inhalt, Belege, Hinweise und Überstimmungen", () => {
    const v: Vorbereitung = {
      event_id: "01X", signing_input: "", event_hash: "6d683a0e7c6a0a85eac96b2fab37ee02",
      inhalt: { von: "Senat Musterhafen", nach: "Nordlicht Analytik GmbH", belege: [{}, {}], ende: null },
      ueberstimmungen: [{ code: "quelle_ohne_archiv", begruendung: "…" }],
      hinweise_offen: ["ohne_start"],
    }
    const text = zusammenfassung(v)
    expect(text).toContain("von: Senat Musterhafen")
    expect(text).toContain("belege: 2")
    expect(text).toContain("Offene Hinweise: ohne_start")
    expect(text).toContain("quelle_ohne_archiv: …")
    expect(text).not.toContain("ende:")
  })
})

describe("Veröffentlichung und Wiederholung", () => {
  it("warnt, dass Begründungen veröffentlicht werden", () => {
    expect(begruendungsFrage({ code: "verdacht_privatperson", text: "Kein Verdacht gegen Privatpersonen." }))
      .toContain(HINWEIS_VEROEFFENTLICHUNG)
    const v: Vorbereitung = { event_id: "", signing_input: "", event_hash: "ab", inhalt: {}, ueberstimmungen: [],
      hinweise_offen: [] }
    expect(zusammenfassung(v)).toContain(HINWEIS_VEROEFFENTLICHUNG)
  })
  it("wiederholt nur, wenn sich allein die Kette bewegt hat", () => {
    expect(ketteVeraendert(new AkteFehler(409, { kette_veraendert: true }))).toBe(true)
    expect(ketteVeraendert(new AkteFehler(409, { detail: "Inhalt geändert" }))).toBe(false)
    expect(ketteVeraendert(new Error("x"))).toBe(false)
  })
})

describe("zusammenfassung zeigt, was unterschrieben wird", () => {
  it("jeden Beleg mit Quelle, Archiv, Zitat und Kopie", () => {
    const v: Vorbereitung = {
      event_id: "", signing_input: "", event_hash: "ab", hinweise_offen: [], ueberstimmungen: [],
      inhalt: { beschreibung: "beauftragt", belege: [{ quelle: { titel: "Drucksache 9/1234",
        url: "https://buergerschaft.beispiel.test/d.pdf", archiv_url: "https://web.archive.org/web/1/x" },
        zitat_woertlich: "Der Senat beauftragt", original_sha256: "ab".repeat(32) }] },
    }
    const text = zusammenfassung(v)
    for (const teil of ["Drucksache 9/1234", "buergerschaft.beispiel.test", "web.archive.org", "„Der Senat beauftragt“",
      "SHA-256 abababab"]) {
      expect(text).toContain(teil)
    }
  })
})
