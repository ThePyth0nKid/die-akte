// Unterschreiben im Browser: Freigabe heißt Unterschrift.
//
// Der Schlüssel ist ein Ed25519-Paar aus WebCrypto. Der private Teil ist nicht exportierbar und liegt nur in der
// IndexedDB dieses Browsers; der Server kennt nur den öffentlichen Schlüssel. Bei der Freigabe bereitet der Server
// das Ereignis vor, dieser Browser unterschreibt genau die gelieferten Bytes, der Server prüft die Unterschrift.

import { authFetch } from "@/lib/api"
import { AkteFehler } from "./api"

const DB = "die-akte"
const SPEICHER = "schluessel"
const BASIS = "/api/v1/akte/beweis"

type Gespeichert = { kid: string; paar: CryptoKeyPair }

export type Vorbereitung = {
  event_id: string
  signing_input: string
  event_hash: string
  inhalt: Record<string, unknown>
  ueberstimmungen: { code: string; begruendung: string }[]
  hinweise_offen: string[]
}

export type FehlendeBegruendung = { code: string; text: string }

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

async function lesen(konto: string): Promise<Gespeichert | undefined> {
  const d = await db()
  return new Promise((ok, nein) => {
    const r = d.transaction(SPEICHER).objectStore(SPEICHER).get(konto)
    r.onsuccess = () => ok(r.result as Gespeichert | undefined)
    r.onerror = () => nein(r.error)
  })
}

async function schreiben(konto: string, wert: Gespeichert): Promise<void> {
  const d = await db()
  return new Promise((ok, nein) => {
    const t = d.transaction(SPEICHER, "readwrite")
    t.objectStore(SPEICHER).put(wert, konto)
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

/** Schlüssel dieses Browsers für dieses Konto: laden oder einmalig erzeugen und beim Server anmelden. */
export async function meinSchluessel(konto = "standard"): Promise<Gespeichert> {
  const vorhanden = await lesen(konto)
  if (vorhanden) return vorhanden
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
  await schreiben(konto, neu)
  return neu
}

export async function vorbereiten(objekt: "karte" | "faden", id: number, kid: string,
  ueberstimmungen: Record<string, string> = {}): Promise<Vorbereitung> {
  return post<Vorbereitung>("/freigabe/vorbereiten/", { objekt, id, kid, ueberstimmungen })
}

/** Genau die vom Server gelieferten Bytes unterschreiben und die Freigabe abschließen. */
export async function unterschreiben(v: Vorbereitung, schluessel: Gespeichert) {
  const bytes = b64urlLesen(v.signing_input)
  const signatur = new Uint8Array(await crypto.subtle.sign({ name: "Ed25519" }, schluessel.paar.privateKey, bytes))
  return post<{ event_id: string; event_hash: string; position: number }>(
    "/freigabe/abschliessen/", { event_id: v.event_id, signatur: b64url(signatur) })
}

/**
 * Der ganze Ablauf mit Rückfragen an den Menschen: fehlende Begründungen für sperrende Befunde erfragen, die
 * Zusammenfassung bestätigen lassen, unterschreiben. Gibt false zurück, wenn der Mensch abbricht.
 */
export async function freigebenMitUnterschrift(
  objekt: "karte" | "faden",
  id: number,
  frage: {
    begruendung: (befund: FehlendeBegruendung) => string | null
    bestaetigen: (v: Vorbereitung) => boolean
  },
): Promise<boolean> {
  const schluessel = await meinSchluessel()
  const ueberstimmungen: Record<string, string> = {}
  for (let runde = 0; runde < 3; runde++) {
    try {
      const v = await vorbereiten(objekt, id, schluessel.kid, ueberstimmungen)
      if (!frage.bestaetigen(v)) return false
      await unterschreiben(v, schluessel)
      return true
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
    }
  }
  throw new Error("Freigabe nicht möglich: Befunde blieben offen.")
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
  zeilen.push("", `Ereignis ${v.event_hash.slice(0, 16)}…`)
  return zeilen.join("\n")
}
