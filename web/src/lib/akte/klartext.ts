// Klartext für die Unterschrift: Was ein Mensch mit seinem Schlüssel bestätigt, steht hier in Worten statt in
// Feldnamen und Codes (`typ: lobby`, `aussageart: belegt`, `quelle_ohne_archiv`). Die Bytes, die unterschrieben
// werden, ändert das nicht: Es ist nur die Anzeige (lib/akte/unterschrift.ts bleibt unberührt).

import {
  TYP_NAMEN, VERBINDUNG_NAMEN, type Aussageart, type EntitaetTyp, type VerbindungTyp, type Wand,
} from "./typen"

export type Feld = { name: string; wert: string }

export type BelegKlartext = {
  titel: string
  herausgeber: string
  /** Adresse zum Lesen (versteckte Zeichen sichtbar gemacht). */
  url: string
  /** Dieselbe Adresse als Link – nur http/https ohne versteckte Zeichen, sonst leer (dann nur Text). */
  link: string
  /** Wohin der Link führt (Punycode), und was an der Adresse täuschen könnte. */
  host: string
  linkWarnungen: string[]
  archivUrl: string
  archivLink: string
  zitat: string
  fundstelle: string
  /** Kurz-Prüfsumme der eigenen Kopie, leer = keine eigene Kopie. */
  kopie: string
  primaer: boolean
}

const AUSSAGE_KLARTEXT: Record<Aussageart, string> = {
  belegt: "Belegt – eine Tatsache mit Quelle",
  verdacht: "Verdacht – noch nicht bewiesen",
  meinung: "Meinung – deine Einschätzung",
}

// Zeichen, die Text unsichtbar umdrehen oder verstecken. In einer Quelle oder einem Zitat können sie vortäuschen, dass
// etwas anderes dasteht, als unterschrieben wird. Sie werden als Marke sichtbar: alle Formatzeichen (\p{Cf}: Bidi,
// Null-Breite, Tag-Zeichen, weiches Trennzeichen …), Steuerzeichen außer Tab und Zeilenumbruch (auch U+0085),
// Hangul-Füllzeichen, Zeilen- und Absatztrenner, Variationsselektoren (auch die mongolischen), der unsichtbare
// Grapheme Joiner U+034F, die unsichtbaren Khmer-Vokale U+17B4/U+17B5, das leere Braillezeichen U+2800 und die
// noch nicht vergebenen, aber unsichtbar dargestellten Zeichen U+2065 und U+FFF0–U+FFF8.
// Leerzeichen, die wie Leerzeichen aussehen (geschütztes, schmales), bleiben: Sie stehen in deutschen Texten oft
// („z. B.“, „10 %“) und verstecken nichts. Als Zeichenkette gebaut, weil TypeScript für \p{…} in einem Literal ein
// neueres Ziel verlangt.
const VERSTECKT_MUSTER = "[\\p{Cf}\\u0000-\\u0008\\u000B\\u000C\\u000E-\\u001F\\u007F-\\u009F\\u034F\\u115F\\u1160"
  + "\\u17B4\\u17B5\\u180B-\\u180F\\u2065\\u2800\\u3164\\uFFA0\\uFFF0-\\uFFF8\\u2028\\u2029\\uFE00-\\uFE0F\\u{E0000}-\\u{E007F}"
  + "\\u{E0100}-\\u{E01EF}]"
const versteckt = () => new RegExp(VERSTECKT_MUSTER, "gu")

/** Macht unsichtbare Zeichen als „⟦U+202E⟧“ sichtbar; sonst bleibt der Text, wie er ist. */
export function sichtbarMachen(text: string): string {
  return text.replace(versteckt(), (z) => `⟦U+${(z.codePointAt(0) ?? 0).toString(16).toUpperCase().padStart(4, "0")}⟧`)
}

/** Nur http- und https-Adressen ohne versteckte Zeichen werden zum Link; alles andere (javascript:, data:, …) bleibt Text. */
export function sichererLink(url: string): boolean {
  try {
    const u = new URL(url)
    return (u.protocol === "http:" || u.protocol === "https:") && !versteckt().test(url)
  } catch {
    return false
  }
}

const SCHRIFTEN = ["Latin", "Cyrillic", "Greek", "Armenian", "Hebrew", "Arabic", "Georgian", "Cherokee", "Han",
  "Hiragana", "Katakana", "Hangul", "Thai", "Devanagari"].map((name) => ({ name, muster: new RegExp(`\\p{Script=${name}}`, "u") }))

/** Welche Schriften kommen in den Buchstaben vor? (Ziffern, Punkte, Bindestriche zählen nicht.) */
function schriftenIn(text: string): Set<string> {
  const gefunden = new Set<string>()
  for (const z of text) {
    if (!new RegExp("\\p{L}", "u").test(z)) continue
    gefunden.add(SCHRIFTEN.find((s) => s.muster.test(z))?.name ?? "andere")
  }
  return gefunden
}

export type LinkPruefung = {
  /** Der Server, wie der Browser ihn ansteuert (internationale Namen in Punycode, „xn--…“). */
  host: string
  /** Was vor dem „@“ steht („nutzer@server“) – leer, wenn nichts. Ein Passwort wird nie gezeigt. */
  benutzerinfo: string
  warnungen: string[]
}

/** Zerlegt eine Adresse für die Anzeige: wohin sie wirklich führt, und was daran täuschen könnte. */
export function linkPruefen(url: string): LinkPruefung | null {
  let u: URL
  try {
    u = new URL(url)
  } catch {
    return null
  }
  const warnungen: string[] = []
  const name = (() => { try { return decodeURIComponent(u.username) } catch { return u.username } })()
  const benutzerinfo = name + (u.password ? ":…" : "")
  if (benutzerinfo) {
    warnungen.push(`Vor dem Server steht „${sichtbarMachen(benutzerinfo)}@“. Der Link führt zu ${u.hostname}, nicht zu „${sichtbarMachen(benutzerinfo)}“.`)
  }
  // Der Name, wie er in der Adresse steht (vor der Umwandlung in Punycode): ohne Schema, Benutzerinfo, Port, Pfad.
  const autoritaet = url.replace(/^[a-z][a-z0-9+.-]*:\/\//i, "").split(/[/?#\\]/)[0]
  const hostRoh = autoritaet.slice(autoritaet.lastIndexOf("@") + 1).replace(/:\d*$/, "")
  if (schriftenIn(hostRoh).size > 1) {
    warnungen.push("Der Servername mischt Schriften (etwa lateinische und kyrillische Buchstaben). So sehen gefälschte Adressen aus.")
  }
  return { host: u.hostname, benutzerinfo, warnungen }
}

/** „2024-06-25“ → „25.06.2024“; was kein Datum ist, bleibt, wie es ist. */
export function datumDeutsch(wert: unknown): string {
  if (typeof wert !== "string" || !wert) return ""
  const t = /^(\d{4})-(\d{2})-(\d{2})/.exec(wert)
  return t ? `${t[3]}.${t[2]}.${t[1]}` : wert
}

const text = (w: unknown) => sichtbarMachen(typeof w === "string" ? w.trim() : typeof w === "number" ? String(w) : "")
const jaNein = (w: unknown) => (w ? "Ja" : "Nein")

/** Die Angaben einer Freigabe in Klartext, in der Reihenfolge, in der ein Mensch sie liest. */
export function unterschriftFelder(objekt: "karte" | "faden", inhalt: Record<string, unknown>): Feld[] {
  const felder: Feld[] = []
  const dazu = (name: string, wert: string) => { if (wert) felder.push({ name, wert }) }
  if (objekt === "karte") {
    const typ = text(inhalt.typ) as EntitaetTyp
    dazu("Name", text(inhalt.name) || "–")
    dazu("Art", TYP_NAMEN[typ] ?? typ)
    dazu("Kurzbeschreibung", text(inhalt.kurzbeschreibung))
    if (typ === "person") {
      dazu("Person des öffentlichen Lebens",
        inhalt.oeffentliche_person ? "Ja" : "Nein – erscheint öffentlich nur mit Initialen")
    }
    dazu("Bild", text(inhalt.bild_url))
    dazu("Bildnachweis", text(inhalt.bild_nachweis))
    return felder
  }
  const typ = text(inhalt.typ) as VerbindungTyp
  const art = text(inhalt.aussageart) as Aussageart
  dazu("Von", text(inhalt.von) || "–")
  dazu("Nach", text(inhalt.nach) || "–")
  dazu("Art der Verbindung", VERBINDUNG_NAMEN[typ] ?? typ)
  felder.push({ name: "Beschriftung", wert: text(inhalt.beschreibung) || "– (keine)" })
  dazu("Aussage", AUSSAGE_KLARTEXT[art] ?? art)
  felder.push({ name: "Seit", wert: datumDeutsch(inhalt.start) || "nicht angegeben" })
  dazu("Bis", datumDeutsch(inhalt.ende))
  felder.push({ name: "Besteht heute noch", wert: jaNein(inhalt.aktuell) })
  const betrag = text(inhalt.betrag)
  if (betrag) dazu("Betrag", `${betrag} ${text(inhalt.waehrung)}`.trim())
  dazu("Anhörung angefragt am", datumDeutsch(inhalt.anhoerung_angefragt_am))
  dazu("Antwort der Person", text(inhalt.anhoerung_antwort))
  dazu("Antwort am", datumDeutsch(inhalt.anhoerung_antwort_am))
  return felder
}

/** Die Belege einer Faden-Freigabe: Quelle, Zitat, Fundstelle und ob eine eigene Kopie gesichert ist. */
export function belegeKlartext(inhalt: Record<string, unknown>): BelegKlartext[] {
  const roh = Array.isArray(inhalt.belege) ? inhalt.belege : []
  return roh.map((b) => {
    const beleg = (b && typeof b === "object" ? b : {}) as Record<string, unknown>
    const q = (beleg.quelle && typeof beleg.quelle === "object" ? beleg.quelle : {}) as Record<string, unknown>
    const sha = text(beleg.original_sha256)
    const roh = (w: unknown) => (typeof w === "string" ? w.trim() : "")
    const pruefung = roh(q.url) ? linkPruefen(roh(q.url)) : null
    return {
      titel: text(q.titel) || "(Quelle ohne Titel)",
      herausgeber: text(q.herausgeber),
      url: text(q.url),
      link: sichererLink(roh(q.url)) ? roh(q.url) : "",
      host: pruefung?.host ?? "",
      linkWarnungen: pruefung?.warnungen ?? [],
      archivUrl: text(q.archiv_url),
      archivLink: sichererLink(roh(q.archiv_url)) ? roh(q.archiv_url) : "",
      zitat: text(beleg.zitat_woertlich),
      fundstelle: text(beleg.fundstelle),
      kopie: sha ? sha.slice(0, 12) : "",
      primaer: q.guete === "primaer",
    }
  })
}

// ─── Hinweise der Prüfung ───────────────────────────────────────────────────

const HINWEISE: Record<string, string> = {
  ohne_quelle: "Der Faden hat noch keinen Beleg (keine Quelle).",
  quelle_ohne_adresse: "Eine Quelle hat weder Link noch Datei.",
  quelle_ohne_abruf: "Bei einer Quelle fehlt das Datum, an dem du sie abgerufen hast.",
  quelle_ohne_archiv: "Eine Quelle hat keine öffentliche Archivkopie (etwa bei archive.org).",
  verdacht_ohne_anhoerung: "Verdacht gegen eine Person, aber die Person wurde nicht angehört.",
  verdacht_zu_duenn: "Für einen Verdacht braucht es mindestens zwei unabhängige Quellen.",
  ohne_start: "Es fehlt, seit wann die Verbindung besteht (Startdatum).",
  zeitraum_widerspruch: "„Besteht heute noch“ und ein Enddatum widersprechen sich.",
  zeitraum_offen: "Unklar, ob die Verbindung heute noch besteht: weder „Besteht heute noch“ noch ein Enddatum.",
  zeitraum_verkehrt: "Das Enddatum liegt vor dem Startdatum.",
  verdacht_privatperson: "Ein Verdacht gegen eine Privatperson geht nie an die Öffentlichkeit.",
  familie_privatperson: "Familienbande von Privatpersonen bleiben intern.",
  veraendert_seit_freigabe: "Seit der letzten Unterschrift geändert: Es braucht eine neue Unterschrift.",
  faden_nicht_freigegeben: "Der Faden ist noch nicht unterschrieben.",
  karte_nicht_freigegeben: "Eine Karte an diesem Faden ist noch nicht unterschrieben.",
}

/** Ein Prüf-Code in Worten. Unbekannte Codes bekommen den Text der Prüfung oder eine lesbare Fassung des Codes. */
export function hinweisKlartext(code: string, textDerPruefung?: string): string {
  if (HINWEISE[code]) return HINWEISE[code]
  if (textDerPruefung?.trim()) return sichtbarMachen(textDerPruefung.trim())
  const lesbar = sichtbarMachen(code.replace(/_/g, " ").trim())
  return lesbar ? `Hinweis der Prüfung: ${lesbar.charAt(0).toUpperCase()}${lesbar.slice(1)}.` : "Hinweis der Prüfung."
}

// ─── Zähler oben: wie viel ist unterschrieben? ──────────────────────────────

export type Zaehler = { unterschrieben: number; entwuerfe: number; karten: [number, number]; faeden: [number, number] }

/** Karten und sichtbare Fäden der Wand: unterschrieben (freigegeben) gegen Entwürfe. */
export function unterschriftZaehler(w: Pick<Wand, "karten" | "faeden"> | null | undefined): Zaehler {
  const karten = w?.karten ?? []
  const faeden = (w?.faeden ?? []).filter((f) => !f.ausgeblendet)
  const kFrei = karten.filter((k) => k.entitaet_detail.status === "freigegeben").length
  const fFrei = faeden.filter((f) => f.status === "freigegeben").length
  return {
    unterschrieben: kFrei + fFrei,
    entwuerfe: karten.length - kFrei + faeden.length - fFrei,
    karten: [kFrei, karten.length],
    faeden: [fFrei, faeden.length],
  }
}

export function zaehlerText(z: Zaehler): string {
  return `${z.unterschrieben} unterschrieben · ${z.entwuerfe} ${z.entwuerfe === 1 ? "Entwurf" : "Entwürfe"}`
}
