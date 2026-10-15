// Erstes Konto im Browser: Prüfung der Eingaben und deutsche Fehlertexte zu den Antworten des Backends
// (POST /api/v1/auth/einrichtung/, über die Next-Route /api/auth/einrichtung).

export type EinrichtungFeld = "code" | "benutzername" | "passwort" | "wiederholung"

export interface EinrichtungEingabe {
  code: string
  benutzername: string
  passwort: string
  wiederholung: string
  archivOrg: boolean
}

export type FeldFehler = Partial<Record<EinrichtungFeld, string>>

/** Wie backend/aktesite/settings.py (MinimumLengthValidator). Das Backend prüft ohnehin selbst. */
export const PASSWORT_MIN = 10

/** Der Code ohne Bindestrich und Leerzeichen, in Großbuchstaben (so vergleicht auch das Backend). */
export function codeNormalisieren(code: string): string {
  return code.toUpperCase().replace(/[^A-Z0-9]/g, "")
}

/**
 * Der Starter öffnet `/akte/einrichten#code=ABCD-EF23`: Das Fragment geht nie an einen Server und steht in keinem Log.
 * Liefert den Code für das Feld (Anzeige-Form) oder null. Das Fragment löscht die Seite danach sofort.
 */
export function codeAusFragment(hash: string): string | null {
  const roh = new URLSearchParams(hash.replace(/^#/, "")).get("code")
  const code = roh ? codeAnzeigen(roh) : ""
  return code || null
}

/** Anzeige beim Tippen: höchstens 8 Zeichen, nach dem vierten ein Bindestrich („ABCD-EF23“). */
export function codeAnzeigen(code: string): string {
  const roh = codeNormalisieren(code).slice(0, 8)
  return roh.length > 4 ? `${roh.slice(0, 4)}-${roh.slice(4)}` : roh
}

const BENUTZERNAME = /^[\p{L}\p{N}_.@+-]+$/u

/** Prüft, was sich ohne Server prüfen lässt. Leeres Ergebnis = alles in Ordnung. */
export function einrichtungPruefen(e: EinrichtungEingabe): FeldFehler {
  const f: FeldFehler = {}
  const code = codeNormalisieren(e.code)
  if (!code) f.code = "Der Einrichtungscode fehlt. Starte START-AKTE noch einmal, dann öffnet sich diese Seite mit dem Code."
  else if (code.length !== 8) f.code = "Der Einrichtungscode hat 8 Zeichen, zum Beispiel ABCD-EF23."
  const name = e.benutzername.trim()
  if (!name) f.benutzername = "Bitte einen Benutzernamen wählen."
  else if (name.length > 150) f.benutzername = "Der Benutzername ist zu lang (höchstens 150 Zeichen)."
  else if (!BENUTZERNAME.test(name)) {
    f.benutzername = "Nur Buchstaben, Ziffern und die Zeichen . @ + - _ – ohne Leerzeichen."
  }
  if (!e.passwort) f.passwort = "Bitte ein Passwort wählen."
  else if (e.passwort.length < PASSWORT_MIN) f.passwort = `Das Passwort ist zu kurz: mindestens ${PASSWORT_MIN} Zeichen.`
  if (e.passwort && e.wiederholung !== e.passwort) f.wiederholung = "Die beiden Passwörter sind nicht gleich."
  return f
}

/** Was an das Backend geht (über die Next-Route). */
export function einrichtungDaten(e: EinrichtungEingabe) {
  return {
    code: codeNormalisieren(e.code),
    benutzername: e.benutzername.trim(),
    passwort: e.passwort,
    archiv_org: e.archivOrg,
  }
}

export interface EinrichtungAntwort {
  meldung: string
  felder: FeldFehler
  /** Die Akte hat schon ein Konto: Weg zum Login zeigen. */
  schonEingerichtet: boolean
}

const liste = (w: unknown) =>
  (Array.isArray(w) ? w : [w]).filter((x) => typeof x === "string" && x.trim()).join(" ")

/**
 * Deutscher Text zu einer Fehlerantwort. Das Backend liefert `{"fehler": …, "felder": {…}}` mit deutschen Texten;
 * englische `detail`-Texte (etwa von der Drossel) werden nicht gezeigt, sondern durch eigene Sätze ersetzt.
 */
export function einrichtungFehler(status: number, daten: unknown): EinrichtungAntwort {
  const d = (daten && typeof daten === "object" ? daten : {}) as { fehler?: unknown; felder?: Record<string, unknown> }
  const fehler = typeof d.fehler === "string" && d.fehler.trim() ? d.fehler.trim() : ""
  const felder: FeldFehler = {}
  for (const [feld, wert] of Object.entries(d.felder ?? {})) {
    const text = liste(wert)
    if (!text) continue
    if (feld === "passwort" || feld === "password") felder.passwort = text
    else if (feld === "benutzername" || feld === "username") felder.benutzername = text
    else if (feld === "code") felder.code = text
  }
  const antwort = (meldung: string, schonEingerichtet = false) => ({ meldung, felder, schonEingerichtet })
  switch (status) {
    case 400:
      return antwort(fehler || (Object.keys(felder).length ? "Bitte prüfe die markierten Felder." : "Die Angaben sind unvollständig."))
    case 403:
      // Ohne deutschen `fehler` kommt die 403 nicht von der Code-Prüfung, sondern von der Herkunftsprüfung (E10).
      if (!fehler) {
        return antwort("Die Akte hat die Anfrage abgelehnt, weil sie nicht von dieser Seite kam. Öffne die Seite direkt "
          + "(Adresse der Akte, dann /akte/einrichten) und versuche es noch einmal.")
      }
      // Nur der falsche Code markiert das Feld; „kein Einrichtungscode gesetzt“ (Einrichtung aus) liegt nicht am Code.
      if (/einrichtungscode stimmt nicht/i.test(fehler)) felder.code = "Dieser Code passt nicht."
      return antwort(fehler)
    case 415:
      return antwort("Die Anfrage kam in einem Format an, das die Akte nicht annimmt. Lade die Seite neu und versuche es "
        + "noch einmal.")
    case 409:
      return antwort(fehler || "Die Akte ist schon eingerichtet. Bitte anmelden.", true)
    case 404:
      return antwort("Diese Version der Akte kennt die Einrichtung im Browser noch nicht. Bitte die Akte aktualisieren.")
    case 429:
      // Die Drossel von DRF antwortet englisch (`detail`), die eigene Sperre des Backends deutsch (`fehler`).
      return antwort(fehler || "Zu viele Versuche. Bitte warte eine Minute und versuche es dann noch einmal.")
    case 0: case 502: case 503: case 504:
      return antwort(fehler || "Die Akte ist gerade nicht erreichbar. Läuft sie noch? Sonst neu starten (START-AKTE).")
    default:
      return antwort(fehler || `Das hat nicht geklappt (Fehler ${status}). Bitte versuche es noch einmal.`)
  }
}

/** offen · zu (schon eingerichtet) · kein_code (nie eingerichtet, aber ohne Einrichtungscode) · unerreichbar */
export type EinrichtungZustand = "offen" | "zu" | "kein_code" | "unerreichbar"

/** Deutet `{"offen", "grund"}` vom Backend. Ohne `grund` (ältere Akte) wie bisher: offen oder zu. */
export function einrichtungDeuten(d: unknown): Exclude<EinrichtungZustand, "unerreichbar"> {
  const { offen, grund } = (d && typeof d === "object" ? d : {}) as { offen?: unknown; grund?: unknown }
  if (offen === true) return "offen"
  return grund === "kein_code" ? "kein_code" : "zu"
}

/** Ist die Einrichtung offen (Code gesetzt, noch kein Konto der Redaktion)? Wenn nicht: warum? */
export async function einrichtungZustand(signal?: AbortSignal): Promise<EinrichtungZustand> {
  try {
    const res = await fetch("/api/auth/einrichtung", { cache: "no-store", credentials: "include", signal })
    // Nur eine 200 ist maßgeblich. Drossel (429), Serverfehler oder eine fremde Antwort heißen „gerade nicht
    // erreichbar, gleich noch mal“ – nie „schon eingerichtet“.
    if (res.status !== 200) return "unerreichbar"
    return einrichtungDeuten(await res.json())
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e
    return "unerreichbar"
  }
}
