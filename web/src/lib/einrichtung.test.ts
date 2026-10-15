// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest"
import {
  codeAnzeigen, codeAusFragment, codeNormalisieren, einrichtungDaten, einrichtungDeuten, einrichtungFehler,
  einrichtungPruefen, einrichtungZustand, type EinrichtungEingabe,
} from "./einrichtung"

const gut: EinrichtungEingabe = {
  code: "abcd-ef23", benutzername: "erika", passwort: "lang-genug-123", wiederholung: "lang-genug-123", archivOrg: false,
}

describe("Einrichtungscode", () => {
  it("vergleicht ohne Bindestrich und Groß-/Kleinschreibung", () => {
    expect(codeNormalisieren(" abcd-ef23 ")).toBe("ABCDEF23")
    expect(codeNormalisieren("ABCD EF23")).toBe("ABCDEF23")
  })
  it("zeigt beim Tippen XXXX-XXXX und höchstens 8 Zeichen", () => {
    expect(codeAnzeigen("abc")).toBe("ABC")
    expect(codeAnzeigen("abcde")).toBe("ABCD-E")
    expect(codeAnzeigen("abcd-ef23zz")).toBe("ABCD-EF23")
  })
})

describe("Code aus dem Fragment (Starter öffnet /akte/einrichten#code=…)", () => {
  it("liest den Code und bringt ihn in die Anzeige-Form", () => {
    expect(codeAusFragment("#code=K7QM-3XPA")).toBe("K7QM-3XPA")
    expect(codeAusFragment("#code=k7qm3xpa")).toBe("K7QM-3XPA")
    expect(codeAusFragment("code=k7qm%203xpa&x=1")).toBe("K7QM-3XPA")
  })
  it("liefert null ohne oder mit leerem Code", () => {
    expect(codeAusFragment("")).toBeNull()
    expect(codeAusFragment("#")).toBeNull()
    expect(codeAusFragment("#code=")).toBeNull()
    expect(codeAusFragment("#andere=1")).toBeNull()
    expect(codeAusFragment("#code=---")).toBeNull()
  })
})

describe("einrichtungDeuten", () => {
  it("unterscheidet offen, eingerichtet und ohne Code", () => {
    expect(einrichtungDeuten({ offen: true, grund: "offen" })).toBe("offen")
    expect(einrichtungDeuten({ offen: false, grund: "eingerichtet" })).toBe("zu")
    expect(einrichtungDeuten({ offen: false, grund: "kein_code" })).toBe("kein_code")
  })
  it("ohne grund (ältere Akte) wie bisher", () => {
    expect(einrichtungDeuten({ offen: true })).toBe("offen")
    expect(einrichtungDeuten({ offen: false })).toBe("zu")
    expect(einrichtungDeuten(null)).toBe("zu")
  })
})

describe("einrichtungZustand: nur eine 200 ist maßgeblich (SR-F4)", () => {
  afterEach(() => { vi.unstubAllGlobals() })
  const mit = (status: number, daten: unknown) =>
    vi.stubGlobal("fetch", vi.fn(async () => new Response(status === 204 ? null : JSON.stringify(daten), { status })))
  it("200 wird gedeutet", async () => {
    mit(200, { offen: true, grund: "offen" })
    expect(await einrichtungZustand()).toBe("offen")
    mit(200, { offen: false, grund: "eingerichtet" })
    expect(await einrichtungZustand()).toBe("zu")
  })
  it("Drossel, Serverfehler und Fremdes heißen „gerade nicht erreichbar“, nie „schon eingerichtet“", async () => {
    for (const status of [429, 500, 502, 503, 404, 403, 204]) {
      mit(status, { offen: false, grund: "eingerichtet" })
      expect(await einrichtungZustand()).toBe("unerreichbar")
    }
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Netz weg") }))
    expect(await einrichtungZustand()).toBe("unerreichbar")
  })
})

describe("einrichtungPruefen", () => {
  it("lässt vollständige Angaben durch", () => {
    expect(einrichtungPruefen(gut)).toEqual({})
  })
  it("verlangt alle Felder, mit deutschem Hinweis je Feld", () => {
    const f = einrichtungPruefen({ code: "", benutzername: " ", passwort: "", wiederholung: "", archivOrg: false })
    expect(Object.keys(f).sort()).toEqual(["benutzername", "code", "passwort"])
    expect(f.code).toContain("START-AKTE")
  })
  it("prüft Codelänge, Benutzername, Passwortlänge und Wiederholung", () => {
    expect(einrichtungPruefen({ ...gut, code: "ABC-123" }).code).toContain("8 Zeichen")
    expect(einrichtungPruefen({ ...gut, benutzername: "Erika Muster" }).benutzername).toContain("ohne Leerzeichen")
    expect(einrichtungPruefen({ ...gut, benutzername: "jürgen.ö" })).toEqual({})
    expect(einrichtungPruefen({ ...gut, passwort: "kurz", wiederholung: "kurz" }).passwort).toContain("mindestens 10")
    expect(einrichtungPruefen({ ...gut, wiederholung: "anders-lang-123" }).wiederholung).toBe("Die beiden Passwörter sind nicht gleich.")
  })
})

describe("einrichtungDaten", () => {
  it("schickt den Code normalisiert und archive.org standardmäßig aus", () => {
    expect(einrichtungDaten({ ...gut, benutzername: "  erika " })).toEqual({
      code: "ABCDEF23", benutzername: "erika", passwort: "lang-genug-123", archiv_org: false,
    })
  })
})

describe("einrichtungFehler: klare deutsche Texte aus den Antworten", () => {
  it("falscher Code (403)", () => {
    const a = einrichtungFehler(403, { fehler: "Einrichtungscode stimmt nicht." })
    expect(a.meldung).toBe("Einrichtungscode stimmt nicht.")
    expect(a.schonEingerichtet).toBe(false)
    expect(a.felder.code).toBeTruthy()
  })
  it("403 ohne deutschen Fehler ist die Herkunftsprüfung, nicht der Code (E10)", () => {
    const a = einrichtungFehler(403, { detail: "You do not have permission to perform this action." })
    expect(a.meldung).toContain("nicht von dieser Seite")
    expect(a.felder.code).toBeUndefined()
    expect(einrichtungFehler(403, { fehler: "Anfrage von fremder Herkunft abgelehnt." }).felder.code).toBeUndefined()
  })
  it("Einrichtung aus (kein Code gesetzt) markiert nicht das Code-Feld", () => {
    const a = einrichtungFehler(403, {
      fehler: "Die Einrichtung im Browser ist aus: Es ist kein Einrichtungscode gesetzt. Starte die Akte mit dem "
        + "Starter (START-AKTE), dann gibt es einen.",
    })
    expect(a.meldung).toContain("kein Einrichtungscode gesetzt")
    expect(a.felder.code).toBeUndefined()
  })
  it("415 (kein JSON) mit eigenem Satz statt englischem Text (E10)", () => {
    const a = einrichtungFehler(415, { detail: 'Unsupported media type "text/plain" in request.' })
    expect(a.meldung).toContain("Format")
    expect(a.meldung).not.toContain("Unsupported")
  })
  it("schon eingerichtet (409) zeigt den Weg zum Login", () => {
    const a = einrichtungFehler(409, { fehler: "Die Akte ist schon eingerichtet. Bitte anmelden." })
    expect(a).toMatchObject({ meldung: "Die Akte ist schon eingerichtet. Bitte anmelden.", schonEingerichtet: true })
  })
  it("Passwortprüfer (400) landen am Feld", () => {
    const a = einrichtungFehler(400, {
      fehler: "Das Passwort ist zu schwach.",
      felder: { passwort: ["Dieses Passwort ist zu üblich.", "Dieses Passwort ist komplett numerisch."] },
    })
    expect(a.meldung).toBe("Das Passwort ist zu schwach.")
    expect(a.felder.passwort).toBe("Dieses Passwort ist zu üblich. Dieses Passwort ist komplett numerisch.")
    expect(einrichtungFehler(400, { felder: { benutzername: ["Vergeben."] } })).toMatchObject({
      meldung: "Bitte prüfe die markierten Felder.", felder: { benutzername: "Vergeben." },
    })
  })
  it("ersetzt englische Drossel-Texte und Netzfehler durch eigene Sätze", () => {
    expect(einrichtungFehler(429, { detail: "Request was throttled. Expected available in 42 seconds." }).meldung)
      .toBe("Zu viele Versuche. Bitte warte eine Minute und versuche es dann noch einmal.")
    expect(einrichtungFehler(429, { fehler: "Zu viele Fehlversuche. Bitte in einer Minute erneut." }).meldung)
      .toBe("Zu viele Fehlversuche. Bitte in einer Minute erneut.")
    expect(einrichtungFehler(0, null).meldung).toContain("nicht erreichbar")
    expect(einrichtungFehler(502, {}).meldung).toContain("START-AKTE")
    expect(einrichtungFehler(404, {}).meldung).toContain("aktualisieren")
    expect(einrichtungFehler(500, { detail: "Internal Server Error" }).meldung).toBe(
      "Das hat nicht geklappt (Fehler 500). Bitte versuche es noch einmal.")
  })
})
