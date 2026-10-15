// @vitest-environment node
import { describe, expect, it } from "vitest"
import {
  belegeKlartext, datumDeutsch, hinweisKlartext, linkPruefen, sichererLink, sichtbarMachen, unterschriftFelder,
  unterschriftZaehler, zaehlerText,
} from "./klartext"
import type { Karte, Verbindung } from "./typen"

// So liefert der Server den Inhalt einer Faden-Freigabe (backend/akte/beweisschicht.py, inhalt_faden).
const FADEN = {
  von: "Digitale Gesellschaft e.V.",
  nach: "EU-Verordnung zur Prävention und Bekämpfung des sexuellen Missbrauchs von Kindern",
  typ: "lobby", beschreibung: "lehnt Entwurf ab", aussageart: "belegt", konfidenz: 2,
  start: "2024-06-25", ende: null, aktuell: true, betrag: null, waehrung: "",
  anhoerung_angefragt_am: null, anhoerung_antwort: "", anhoerung_antwort_am: null,
  belege: [{
    quelle: { titel: "Lobbyregister – Regelungsvorhaben RV0005904", url: "https://www.lobbyregister.bundestag.de/x",
      herausgeber: "Deutscher Bundestag", archiv_url: "", guete: "primaer" },
    zitat_woertlich: "Unsere Bemühungen um Einflussnahme beziehen sich im Wesentlichen auf …",
    fundstelle: "Beschreibung, Stand 26.03.2026", original_sha256: "ab12cd34ef56".repeat(5),
  }],
}

describe("unterschriftFelder", () => {
  it("zeigt einen Faden in Klartext statt Rohfeldern", () => {
    const felder = unterschriftFelder("faden", FADEN)
    const je = Object.fromEntries(felder.map((f) => [f.name, f.wert]))
    expect(je).toMatchObject({
      Von: "Digitale Gesellschaft e.V.",
      Nach: FADEN.nach,
      "Art der Verbindung": "Lobby / Beratung",
      Beschriftung: "lehnt Entwurf ab",
      Aussage: "Belegt – eine Tatsache mit Quelle",
      Seit: "25.06.2024",
      "Besteht heute noch": "Ja",
    })
    // keine Rohwerte, keine leeren Zeilen
    const alles = felder.map((f) => `${f.name}: ${f.wert}`).join("\n")
    for (const roh of ["typ:", "lobby\n", "aussageart", "konfidenz", "true", "null"]) expect(alles).not.toContain(roh)
    expect(felder.map((f) => f.name)).not.toContain("Bis")
  })

  it("nennt fehlende Angaben ausdrücklich", () => {
    const je = Object.fromEntries(unterschriftFelder("faden", { ...FADEN, start: null, aktuell: false, beschreibung: "",
      ende: "2025-01-31", aussageart: "verdacht" }).map((f) => [f.name, f.wert]))
    expect(je).toMatchObject({ Seit: "nicht angegeben", Bis: "31.01.2025", "Besteht heute noch": "Nein",
      Beschriftung: "– (keine)", Aussage: "Verdacht – noch nicht bewiesen" })
  })

  it("zeigt eine Karte mit Art und Hinweis zur Privatperson", () => {
    const je = Object.fromEntries(unterschriftFelder("karte", {
      name: "Erika Muster", typ: "person", kurzbeschreibung: "", oeffentliche_person: false, bild_url: "", bild_nachweis: "",
    }).map((f) => [f.name, f.wert]))
    expect(je).toEqual({ Name: "Erika Muster", Art: "Person", "Person des öffentlichen Lebens": "Nein – erscheint öffentlich nur mit Initialen" })
  })
})

describe("belegeKlartext", () => {
  it("bringt Quelle, Zitat, Fundstelle und eigene Kopie", () => {
    const [b] = belegeKlartext(FADEN)
    expect(b).toMatchObject({
      titel: "Lobbyregister – Regelungsvorhaben RV0005904", herausgeber: "Deutscher Bundestag",
      url: "https://www.lobbyregister.bundestag.de/x", zitat: FADEN.belege[0].zitat_woertlich,
      fundstelle: "Beschreibung, Stand 26.03.2026", kopie: "ab12cd34ef56", primaer: true, archivUrl: "",
    })
  })
  it("verträgt kaputte oder fehlende Belege", () => {
    expect(belegeKlartext({})).toEqual([])
    expect(belegeKlartext({ belege: [null, { quelle: "x" }] })[0].titel).toBe("(Quelle ohne Titel)")
  })
})

describe("versteckte Zeichen und unsichere Links (SR6, SR12)", () => {
  it("macht Bidi- und Null-Breite-Zeichen sichtbar", () => {
    expect(sichtbarMachen("Zahlung ‮überwiesen")).toBe("Zahlung ⟦U+202E⟧überwiesen")
    expect(sichtbarMachen("a​b﻿")).toBe("a⟦U+200B⟧b⟦U+FEFF⟧")
    expect(sichtbarMachen("ganz normal – „Zitat“")).toBe("ganz normal – „Zitat“")
  })
  it("erfasst alle Formatzeichen, Füllzeichen, Zeilentrenner, Tags und Variationsselektoren (SR-F7)", () => {
    expect(sichtbarMachen("Ver\u00ADordnung")).toBe("Ver⟦U+00AD⟧ordnung")
    expect(sichtbarMachen("a\u3164b\u115Fc\uFFA0")).toBe("a⟦U+3164⟧b⟦U+115F⟧c⟦U+FFA0⟧")
    expect(sichtbarMachen("Zeile\u2028Absatz\u2029")).toBe("Zeile⟦U+2028⟧Absatz⟦U+2029⟧")
    expect(sichtbarMachen("x\u{E0041}\u{E007F}")).toBe("x⟦U+E0041⟧⟦U+E007F⟧")
    expect(sichtbarMachen("Herz\uFE0F\u{E0100}")).toBe("Herz⟦U+FE0F⟧⟦U+E0100⟧")
    expect(sichtbarMachen("Straße ✓ 😀 日本")).toBe("Straße ✓ 😀 日本")
  })
  it("erfasst Steuerzeichen, Grapheme Joiner, Khmer- und Braille-Leere, aber nicht Tab, Umbruch und schmale Leerzeichen", () => {
    expect(sichtbarMachen("a\u0085b\u001Bc\u007F")).toBe("a⟦U+0085⟧b⟦U+001B⟧c⟦U+007F⟧")
    expect(sichtbarMachen("x͏y឴z឵")).toBe("x⟦U+034F⟧y⟦U+17B4⟧z⟦U+17B5⟧")
    expect(sichtbarMachen("m᠋n⠀")).toBe("m⟦U+180B⟧n⟦U+2800⟧")
    expect(sichtbarMachen("p⁥q￰")).toBe("p⟦U+2065⟧q⟦U+FFF0⟧")
    expect(sichtbarMachen("Zeile 1\r\n\tZeile 2\nz. B. 10 %")).toBe("Zeile 1\r\n\tZeile 2\nz. B. 10 %")
  })
  it("lässt nur http und https als Link zu", () => {
    expect(sichererLink("https://www.bundestag.de/x")).toBe(true)
    expect(sichererLink("http://localhost:8080/a")).toBe(true)
    expect(sichererLink("javascript:alert(1)")).toBe(false)
    expect(sichererLink("data:text/html,<b>x</b>")).toBe(false)
    expect(sichererLink("https://exa‮mple.org")).toBe(false)
    expect(sichererLink("kein link")).toBe(false)
  })
  it("Felder und Belege zeigen versteckte Zeichen, unsichere Adressen werden kein Link", () => {
    const [b] = belegeKlartext({ belege: [{ quelle: { titel: "Bericht‮txt.exe", url: "javascript:alert(1)" },
      zitat_woertlich: "wörtlich​" }] })
    expect(b.titel).toBe("Bericht⟦U+202E⟧txt.exe")
    expect(b.zitat).toBe("wörtlich⟦U+200B⟧")
    expect(b.url).toBe("javascript:alert(1)")
    expect(b.link).toBe("")
    const je = Object.fromEntries(unterschriftFelder("faden", { ...FADEN, beschreibung: "lehnt⁦ ab" }).map((f) => [f.name, f.wert]))
    expect(je.Beschriftung).toBe("lehnt⟦U+2066⟧ ab")
    expect(belegeKlartext(FADEN)[0].link).toBe("https://www.lobbyregister.bundestag.de/x")
  })
})

describe("linkPruefen: wohin ein Link wirklich führt (SR-F7)", () => {
  it("normale Adresse: Server, keine Warnung", () => {
    expect(linkPruefen("https://www.bundestag.de/drucksachen?x=1")).toEqual({ host: "www.bundestag.de", benutzerinfo: "", warnungen: [] })
  })
  it("Benutzerinfo vor dem @ wird getrennt gezeigt und gewarnt, Passwort nie", () => {
    const p = linkPruefen("https://www.bundestag.de:geheim@boese.example/pfad")!  // erfundene Täuschungs-Adresse, scrub:erlaubt
    expect(p.host).toBe("boese.example")
    expect(p.benutzerinfo).toBe("www.bundestag.de:…")
    expect(p.warnungen[0]).toContain("führt zu boese.example")
    expect(p.warnungen.join(" ")).not.toContain("geheim")
  })
  it("internationaler Name als Punycode, gemischte Schriften mit Warnung", () => {
    const p = linkPruefen("https://p\u0430ypal.com/login")!   // kyrillisches „а“
    expect(p.host.startsWith("xn--")).toBe(true)
    expect(p.warnungen.join(" ")).toContain("mischt Schriften")
    const rein = linkPruefen("https://münchen.de/")!
    expect(rein.host).toBe("xn--mnchen-3ya.de")
    expect(rein.warnungen).toEqual([])
  })
  it("Unsinn ist kein Link", () => {
    expect(linkPruefen("kein link")).toBeNull()
  })
})

describe("hinweisKlartext", () => {
  const CODES = [
    "ohne_quelle", "quelle_ohne_adresse", "quelle_ohne_abruf", "quelle_ohne_archiv", "verdacht_ohne_anhoerung",
    "verdacht_zu_duenn", "ohne_start", "zeitraum_widerspruch", "zeitraum_offen", "zeitraum_verkehrt",
    "verdacht_privatperson", "familie_privatperson", "veraendert_seit_freigabe", "faden_nicht_freigegeben",
    "karte_nicht_freigegeben",
  ]
  it("übersetzt jeden Code der Prüfung in einen ganzen Satz ohne Code", () => {
    for (const code of CODES) {
      const text = hinweisKlartext(code)
      expect(text).not.toContain("_")
      expect(text).toMatch(/[.:]$/)
      expect(text.length).toBeGreaterThan(20)
    }
    expect(hinweisKlartext("quelle_ohne_archiv")).toContain("archive.org")
    expect(hinweisKlartext("ohne_start")).toContain("Startdatum")
  })
  it("nimmt für unbekannte Codes den Text der Prüfung oder eine lesbare Fassung", () => {
    expect(hinweisKlartext("neue_regel", "Neue Regel greift.")).toBe("Neue Regel greift.")
    expect(hinweisKlartext("neue_regel")).toBe("Hinweis der Prüfung: Neue regel.")
  })
})

describe("datumDeutsch", () => {
  it("wandelt ISO in TT.MM.JJJJ", () => {
    expect(datumDeutsch("2024-06-25")).toBe("25.06.2024")
    expect(datumDeutsch("2024-06-25T10:00:00Z")).toBe("25.06.2024")
    expect(datumDeutsch(null)).toBe("")
    expect(datumDeutsch("Frühjahr 2024")).toBe("Frühjahr 2024")
  })
})

describe("unterschriftZaehler", () => {
  const karte = (id: number, status: "entwurf" | "freigegeben") => ({
    id, entitaet: id, x: 0, y: 0, farbe: "",
    entitaet_detail: { id, typ: "organisation", name: `K${id}`, slug: "", kurzbeschreibung: "", bild_url: "", oeffentliche_person: false, status },
  }) as Karte
  const faden = (id: number, status: "entwurf" | "freigegeben", ausgeblendet = false) =>
    ({ id, status, ausgeblendet }) as unknown as Verbindung
  it("zählt Karten und sichtbare Fäden", () => {
    const z = unterschriftZaehler({
      karten: [karte(1, "freigegeben"), karte(2, "entwurf")],
      faeden: [faden(1, "freigegeben"), faden(2, "entwurf"), faden(3, "entwurf"), faden(4, "freigegeben", true)],
    })
    expect(z).toEqual({ unterschrieben: 2, entwuerfe: 3, karten: [1, 2], faeden: [1, 3] })
    expect(zaehlerText(z)).toBe("2 unterschrieben · 3 Entwürfe")
    expect(zaehlerText({ ...z, entwuerfe: 1 })).toBe("2 unterschrieben · 1 Entwurf")
    expect(unterschriftZaehler(null)).toMatchObject({ unterschrieben: 0, entwuerfe: 0 })
  })
})
