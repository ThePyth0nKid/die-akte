// Unterschreiben im Browser: Freigabe heißt Unterschrift.
//
// Der Schlüssel ist ein Ed25519-Paar aus WebCrypto. Der private Teil ist nicht exportierbar und liegt nur in der
// IndexedDB dieses Browsers; der Server kennt nur den öffentlichen Schlüssel. Bei der Freigabe bereitet der Server
// das Ereignis vor, dieser Browser unterschreibt genau die gelieferten Bytes, der Server prüft die Unterschrift.
//
// Gespeichert wird je Schlüsselkennung (kid), nicht je Konto: Welche Schlüssel dem angemeldeten Konto gehören, sagt
// der Server. Melden sich in einem Browser zwei Konten an, benutzt jedes nur seine eigenen Schlüssel.

import { authFetch } from "@/lib/api"
import { AkteFehler } from "./api"

const DB = "die-akte"
const SPEICHER = "schluessel"
const BASIS = "/api/v1/akte/beweis"

type Gespeichert = { kid: string; paar: CryptoKeyPair }

export type EigenerSchluessel = {
  kid: string
  fingerabdruck: string
  erstellt_am: string
  widerrufen_am: string | null
}

export type Vorbereitung = {
  event_id: string
  signing_input: string
  event_hash: string
  inhalt: Record<string, unknown>
  ueberstimmungen: { code: string; begruendung: string }[]
  hinweise_offen: string[]
  veroeffentlichung?: string
}

export type FehlendeBegruendung = { code: string; text: string }

export const HINWEIS_VEROEFFENTLICHUNG =
  "Inhalt und Begründungen werden mit der Freigabe veröffentlicht, sobald das Objekt auf einem öffentlichen Board steht."

export function b64url(bytes: Uint8Array): string {
  let s = ""
  for (const b of bytes) s += String.fromCharCode(b)
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")
}

export function b64urlLesen(text: string): Uint8Array<ArrayBuffer> {
  const b64 = text.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((text.length + 3) % 4)
  const roh = atob(b64)
  const bytes = new Uint8Array(new ArrayBuffer(roh.length))
  for (let i = 0; i < roh.length; i++) bytes[i] = roh.charCodeAt(i)
  return bytes
}

function db(): Promise<IDBDatabase> {
  return new Promise((ok, nein) => {
    const r = indexedDB.open(DB, 1)
    r.onupgradeneeded = () => r.result.createObjectStore(SPEICHER)
    r.onsuccess = () => ok(r.result)
    r.onerror = () => nein(r.error)
  })
}

async function lesen(kid: string): Promise<Gespeichert | undefined> {
  const d = await db()
  return new Promise((ok, nein) => {
    const r = d.transaction(SPEICHER).objectStore(SPEICHER).get(kid)
    r.onsuccess = () => ok(r.result as Gespeichert | undefined)
    r.onerror = () => nein(r.error)
  })
}

async function schreiben(wert: Gespeichert): Promise<void> {
  const d = await db()
  return new Promise((ok, nein) => {
    const t = d.transaction(SPEICHER, "readwrite")
    t.objectStore(SPEICHER).put(wert, wert.kid)
    t.oncomplete = () => ok()
    t.onerror = () => nein(t.error)
  })
}

async function entfernen(kid: string): Promise<void> {
  const d = await db()
  return new Promise((ok, nein) => {
    const t = d.transaction(SPEICHER, "readwrite")
    t.objectStore(SPEICHER).delete(kid)
    t.oncomplete = () => ok()
    t.onerror = () => nein(t.error)
  })
}

async function post<T>(pfad: string, daten: unknown): Promise<T> {
  const res = await authFetch(`${BASIS}${pfad}`, { method: "POST", body: JSON.stringify(daten) })
  const inhalt = await res.json().catch(() => ({}))
  if (!res.ok) throw new AkteFehler(res.status, inhalt)
  return inhalt as T
}

/** Die Schlüssel des angemeldeten Kontos laut Server (neueste zuerst), auch widerrufene. */
export async function eigeneSchluessel(): Promise<EigenerSchluessel[]> {
  const res = await authFetch(`${BASIS}/schluessel/`)
  const inhalt = await res.json().catch(() => [])
  if (!res.ok) throw new AkteFehler(res.status, inhalt)
  return inhalt as EigenerSchluessel[]
}

/** Gültiger Schlüssel dieses Kontos in diesem Browser: vorhandenen nehmen oder einmalig erzeugen und anmelden. */
export async function meinSchluessel(): Promise<Gespeichert> {
  for (const s of await eigeneSchluessel()) {
    if (s.widerrufen_am) continue
    const vorhanden = await lesen(s.kid)
    if (vorhanden) return vorhanden
  }
  let paar: CryptoKeyPair
  try {
    paar = (await crypto.subtle.generateKey({ name: "Ed25519" }, false, ["sign", "verify"])) as CryptoKeyPair
  } catch {
    throw new Error("Dieser Browser kann keine Ed25519-Schlüssel erzeugen (aktuelle Versionen von Chrome, Edge, " +
      "Firefox und Safari können es). Ohne Schlüssel keine Freigabe.")
  }
  const roh = new Uint8Array(await crypto.subtle.exportKey("raw", paar.publicKey))
  const { kid } = await post<{ kid: string }>("/schluessel/", { oeffentlich: b64url(roh) })
  const neu = { kid, paar }
  await schreiben(neu)
  return neu
}

/** Liegt der private Teil dieses Schlüssels in diesem Browser? */
export async function hierGespeichert(kid: string): Promise<boolean> {
  return Boolean(await lesen(kid))
}

export async function vorbereiten(objekt: "karte" | "faden", id: number, kid: string,
  ueberstimmungen: Record<string, string> = {}, board?: string): Promise<Vorbereitung> {
  return post<Vorbereitung>("/freigabe/vorbereiten/", { objekt, id, kid, ueberstimmungen, ...(board ? { board } : {}) })
}

async function signieren(signingInput: string, schluessel: Gespeichert): Promise<string> {
  const bytes = b64urlLesen(signingInput)
  return b64url(new Uint8Array(await crypto.subtle.sign({ name: "Ed25519" }, schluessel.paar.privateKey, bytes)))
}

/** Genau die vom Server gelieferten Bytes unterschreiben und die Freigabe abschließen. */
export async function unterschreiben(v: Vorbereitung, schluessel: Gespeichert) {
  return post<{ event_id: string; event_hash: string; position: number }>(
    "/freigabe/abschliessen/", { event_id: v.event_id, signatur: await signieren(v.signing_input, schluessel) })
}

/** Hat sich nur die Kette verändert (anderer Mensch oder eine Sicherung kam dazwischen)? Dann neu vorbereiten. */
export function ketteVeraendert(e: unknown): boolean {
  return e instanceof AkteFehler && e.status === 409
    && Boolean((e.daten as { kette_veraendert?: boolean } | null)?.kette_veraendert)
}

function bestaetigterStand(v: Vorbereitung): string {
  return JSON.stringify([v.inhalt, v.ueberstimmungen, v.hinweise_offen])
}

/**
 * Der ganze Ablauf mit Rückfragen an den Menschen: fehlende Begründungen für sperrende Befunde erfragen, die
 * Zusammenfassung bestätigen lassen, unterschreiben. Hat sich zwischendurch nur die Kette bewegt, wird ohne neue
 * Rückfrage neu vorbereitet, solange der Inhalt genau der bestätigte ist. Gibt false zurück, wenn der Mensch abbricht.
 */
export async function freigebenMitUnterschrift(
  objekt: "karte" | "faden",
  id: number,
  frage: {
    begruendung: (befund: FehlendeBegruendung) => string | null
    bestaetigen: (v: Vorbereitung) => boolean
  },
  board?: string,
): Promise<boolean> {
  const schluessel = await meinSchluessel()
  const ueberstimmungen: Record<string, string> = {}
  let bestaetigt = ""
  for (let runde = 0; runde < 6; runde++) {
    let v: Vorbereitung
    try {
      v = await vorbereiten(objekt, id, schluessel.kid, ueberstimmungen, board)
    } catch (e) {
      const fehlend = e instanceof AkteFehler
        ? ((e.daten as { fehlende_begruendung?: FehlendeBegruendung[] })?.fehlende_begruendung ?? [])
        : []
      if (!fehlend.length) throw e
      for (const b of fehlend) {
        const grund = frage.begruendung(b)
        if (!grund || !grund.trim()) return false
        ueberstimmungen[b.code] = grund.trim()
      }
      continue
    }
    if (bestaetigterStand(v) !== bestaetigt) {
      if (!frage.bestaetigen(v)) return false
      bestaetigt = bestaetigterStand(v)
    }
    try {
      await unterschreiben(v, schluessel)
      return true
    } catch (e) {
      if (!ketteVeraendert(e)) throw e
    }
  }
  throw new Error("Freigabe nicht möglich: Die Kette hat sich zu oft verändert oder Befunde blieben offen.")
}

/** Einen eigenen Schlüssel widerrufen (etwa nach Verlust eines Geräts). Unterschrieben wird mit dem Schlüssel
 * dieses Browsers; ist es derselbe, legt die nächste Freigabe einen neuen an. */
export async function widerrufen(kid: string): Promise<void> {
  const mit = await meinSchluessel()
  for (let runde = 0; runde < 3; runde++) {
    const v = await post<{ event_id: string; signing_input: string }>("/widerruf/vorbereiten/", { kid, mit: mit.kid })
    try {
      await post("/widerruf/abschliessen/", { event_id: v.event_id, signatur: await signieren(v.signing_input, mit) })
      if (await lesen(kid)) await entfernen(kid)
      return
    } catch (e) {
      if (!ketteVeraendert(e)) throw e
    }
  }
  throw new Error("Widerruf nicht möglich: Die Kette hat sich zu oft verändert.")
}

/** Frage an den Menschen, wenn ein sperrender Befund eine Begründung braucht. */
export function begruendungsFrage(b: FehlendeBegruendung): string {
  return `Sperrender Befund: ${b.text}\n\nBegründung, warum du ihn überstimmst.\n${HINWEIS_VEROEFFENTLICHUNG}`
}

/** Text für die Bestätigung: Was genau wird unterschrieben? */
export function zusammenfassung(v: Vorbereitung): string {
  const zeilen = ["Du unterschreibst diese Freigabe mit deinem Schlüssel:", ""]
  for (const [k, w] of Object.entries(v.inhalt)) {
    if (k === "belege" && Array.isArray(w)) zeilen.push(`belege: ${w.length}`)
    else if (w !== null && w !== "" && typeof w !== "object") zeilen.push(`${k}: ${String(w)}`)
  }
  if (v.hinweise_offen.length) zeilen.push("", `Offene Hinweise: ${v.hinweise_offen.join(", ")}`)
  if (v.ueberstimmungen.length) zeilen.push("", `Überstimmt: ${v.ueberstimmungen.map((u) => u.code).join(", ")}`)
  zeilen.push("", HINWEIS_VEROEFFENTLICHUNG, `Ereignis ${v.event_hash.slice(0, 16)}…`)
  return zeilen.join("\n")
}
