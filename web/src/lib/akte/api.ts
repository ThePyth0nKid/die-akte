// Die Akte — Aufrufe gegen /api/v1/akte/ über den Proxy (authFetch).
// Ohne Konto liest `lesen` die öffentlichen Boards direkt bei der API.

import { authFetch } from "@/lib/api"
import type {
  Board, Entitaet, EntitaetDetail, EntitaetKurz, Fahrt, Karte, Mappe, Quelle, Rahmen,
  Verbindung, Wand, Zettel,
} from "./typen"

const BASIS = "/api/v1/akte"

// Lesen ohne Konto geht direkt an die API, nicht über den Next.js-Proxy: Der reicht die Besucher-IP nicht weiter,
// die Drossel je IP träfe sonst alle Besucher gemeinsam. Standard ist dieselbe Herkunft (Caddy bzw. die Umleitungen
// in next.config.ts leiten /api/v1 an das Backend); eine getrennte API-Adresse geht über NEXT_PUBLIC_API_BASE.
const API_DIREKT = (process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ?? "") + BASIS

export class AkteFehler extends Error {
  constructor(public status: number, public daten: unknown) {
    super(fehlerText(daten) || `Anfrage fehlgeschlagen (${status})`)
  }
}

function fehlerText(daten: unknown): string {
  if (!daten || typeof daten !== "object") return ""
  return Object.entries(daten as Record<string, unknown>)
    .map(([feld, wert]) => `${feld}: ${Array.isArray(wert) ? wert.join(" ") : String(wert)}`)
    .join(" · ")
}

async function anfrage<T>(pfad: string, init: RequestInit = {}): Promise<T> {
  const res = await authFetch(`${BASIS}${pfad}`, init)
  if (res.status === 204) return undefined as T
  const daten = await res.json().catch(() => null)
  if (!res.ok) throw new AkteFehler(res.status, daten)
  return daten as T
}

/** Lesen mit Konto, sonst ohne: Wer keine Sitzung hat, bekommt die öffentlichen Boards (nur lesen). */
async function lesen<T>(pfad: string): Promise<T> {
  try {
    return await anfrage<T>(pfad)
  } catch (e) {
    // authFetch meldet eine fehlende oder abgelaufene Sitzung so; alles andere ist ein echter Fehler.
    if (!(e instanceof Error) || e instanceof AkteFehler || e.message !== "Session expired") throw e
  }
  const res = await fetch(`${API_DIREKT}${pfad}`, { credentials: "omit" })
  const daten = await res.json().catch(() => null)
  if (!res.ok) throw new AkteFehler(res.status, daten)
  return daten as T
}

async function hochladen<T>(pfad: string, felder: Record<string, string | Blob>): Promise<T> {
  const form = new FormData()
  for (const [k, v] of Object.entries(felder)) form.append(k, v)
  return anfrage<T>(pfad, { method: "POST", body: form })
}

const json = (methode: string, daten: unknown): RequestInit => ({
  method: methode,
  body: JSON.stringify(daten),
})

export const akte = {
  boards: () => lesen<Board[]>("/boards/"),
  boardAnlegen: (daten: Partial<Board>) => anfrage<Board>("/boards/", json("POST", daten)),
  boardAendern: (slug: string, daten: Partial<Board>) =>
    anfrage<Board>(`/boards/${slug}/`, json("PATCH", daten)),
  wand: (slug: string) => lesen<Wand>(`/boards/${slug}/`),

  suchen: (q: string) => anfrage<EntitaetKurz[]>(`/entitaeten/?q=${encodeURIComponent(q)}`),
  entitaet: (id: number) => anfrage<EntitaetDetail>(`/entitaeten/${id}/`),
  entitaetAnlegen: (daten: Partial<Entitaet>) => anfrage<Entitaet>("/entitaeten/", json("POST", daten)),
  entitaetAendern: (id: number, daten: Partial<Entitaet>) =>
    anfrage<Entitaet>(`/entitaeten/${id}/`, json("PATCH", daten)),

  quellenSuchen: (q: string) => anfrage<Quelle[]>(`/quellen/?q=${encodeURIComponent(q)}`),
  quelleAnlegen: (daten: Partial<Quelle>) => anfrage<Quelle>("/quellen/", json("POST", daten)),
  quelle: (id: number) => anfrage<Quelle>(`/quellen/${id}/`),
  quelleSichern: (id: number) => anfrage<{ angestossen: boolean }>(`/quellen/${id}/sichern/`, { method: "POST" }),
  anhang: (id: number, datei: File) => hochladen<Quelle>(`/quellen/${id}/anhang/`, { datei }),
  quelleAusDatei: (datei: File, ort?: { board: string; x: number; y: number }) =>
    hochladen<Quelle>("/quellen/aus-datei/", {
      datei, titel: datei.name.replace(/\.[a-z0-9]+$/i, ""),
      ...(ort ? { board: ort.board, x: String(ort.x), y: String(ort.y) } : {}),
    }),
  dateiUrl: (sicherungId: number) => `/api/proxy${BASIS}/sicherungen/${sicherungId}/datei/`,
  beweisLegen: (slug: string, quelle: number, x: number, y: number) =>
    anfrage<{ id: number }>(`/boards/${slug}/beweise/`, json("POST", { quelle, x, y })),
  beweisEntfernen: (slug: string, id: number) =>
    anfrage<void>(`/boards/${slug}/beweise/${id}/`, { method: "DELETE" }),

  fadenAnlegen: (daten: Partial<Verbindung>) => anfrage<Verbindung>("/verbindungen/", json("POST", daten)),
  fadenAendern: (id: number, daten: Partial<Verbindung>) =>
    anfrage<Verbindung>(`/verbindungen/${id}/`, json("PATCH", daten)),
  fadenLoeschen: (id: number) => anfrage<void>(`/verbindungen/${id}/`, { method: "DELETE" }),
  fadenAusblenden: (slug: string, id: number) =>
    anfrage<{ ausgeblendet: boolean }>(`/boards/${slug}/faeden/${id}/ausblenden/`, { method: "POST" }),

  karteLegen: (slug: string, entitaet: number, x: number, y: number) =>
    anfrage<Karte>(`/boards/${slug}/karten/`, json("POST", { entitaet, x, y })),
  karteEntfernen: (slug: string, id: number) =>
    anfrage<void>(`/boards/${slug}/karten/${id}/`, { method: "DELETE" }),
  zettelAnlegen: (slug: string, daten: Partial<Zettel>) =>
    anfrage<Zettel>(`/boards/${slug}/zettel/`, json("POST", daten)),
  zettelAendern: (slug: string, id: number, daten: Partial<Zettel>) =>
    anfrage<Zettel>(`/boards/${slug}/zettel/${id}/`, json("PATCH", daten)),
  zettelEntfernen: (slug: string, id: number) =>
    anfrage<void>(`/boards/${slug}/zettel/${id}/`, { method: "DELETE" }),
  rahmenAnlegen: (slug: string, daten: Partial<Rahmen>) =>
    anfrage<Rahmen>(`/boards/${slug}/rahmen/`, json("POST", daten)),
  rahmenAendern: (slug: string, id: number, daten: Partial<Rahmen>) =>
    anfrage<Rahmen>(`/boards/${slug}/rahmen/${id}/`, json("PATCH", daten)),
  rahmenEntfernen: (slug: string, id: number) =>
    anfrage<void>(`/boards/${slug}/rahmen/${id}/`, { method: "DELETE" }),
  mappeLegen: (slug: string, ziel: string, x: number, y: number) =>
    anfrage<Pick<Mappe, "id" | "ziel" | "x" | "y" | "farbe">>(`/boards/${slug}/mappen/`, json("POST", { ziel, x, y })),
  mappeEntfernen: (slug: string, id: number) =>
    anfrage<void>(`/boards/${slug}/mappen/${id}/`, { method: "DELETE" }),
  aufraeumen: (slug: string) => anfrage<Wand>(`/boards/${slug}/aufraeumen/`, { method: "POST" }),
  positionen: (slug: string, eintraege: { art: string; id: number; x: number; y: number; breite?: number; hoehe?: number }[]) =>
    anfrage<void>(`/boards/${slug}/positionen/`, json("POST", eintraege)),

  fahrtAnlegen: (slug: string, daten: Omit<Fahrt, "id">) =>
    anfrage<Fahrt>(`/boards/${slug}/fahrten/`, json("POST", daten)),
  fahrtSpeichern: (slug: string, fahrt: Fahrt) =>
    anfrage<Fahrt>(`/boards/${slug}/fahrten/${fahrt.id}/`, json("PUT", fahrt)),
  fahrtLoeschen: (slug: string, id: number) =>
    anfrage<void>(`/boards/${slug}/fahrten/${id}/`, { method: "DELETE" }),

  weg: (von: number, nach: number, nurBelegt: boolean) =>
    anfrage<{ gefunden: boolean; entitaeten: number[]; faeden: number[] }>(
      `/weg/?von=${von}&nach=${nach}${nurBelegt ? "&nur_belegt=1" : ""}`,
    ),
  exportUrl: () => `/api/proxy${BASIS}/export/obsidian/`,
}
