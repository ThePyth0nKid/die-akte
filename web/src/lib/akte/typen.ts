// Typen der Akte — Spiegel von apps/api/akte/serializers.py.

export type EntitaetTyp =
  | "person" | "organisation" | "firma" | "behoerde" | "partei"
  | "ereignis" | "gesetz" | "system" | "ort" | "dokument"

export type Status = "entwurf" | "vorschlag" | "freigegeben"
export type Aussageart = "belegt" | "verdacht" | "meinung"
export type Guete = "primaer" | "sekundaer"

export type VerbindungTyp =
  | "amt" | "eigentum" | "finanzierung" | "mitgliedschaft" | "auftrag"
  | "lobby" | "gesetz_betrifft" | "aussage" | "familie" | "sonstiges"

export interface EntitaetKurz {
  id: number
  typ: EntitaetTyp
  name: string
  slug: string
  kurzbeschreibung: string
  bild_url: string
  /** Foto-Nachweis (Urheber, Lizenz), steht auf der Karte. */
  bild_nachweis?: string
  oeffentliche_person: boolean
  status: Status
}

export interface Entitaet extends EntitaetKurz {
  notiz_md: string
  wikidata_qid: string
  tags: string[]
}

export interface EntitaetDetail extends Entitaet {
  faeden: Verbindung[]
  nachbarn: EntitaetKurz[]
  rueckverweise: EntitaetKurz[]
  /** „Kommt vor in …“: alle Wände, auf denen die Karte liegt. */
  boards?: BoardVerweis[]
}

export type SicherungArt =
  | "original" | "vorschau" | "screenshot" | "seite_pdf" | "fundstelle" | "archive_org" | "video_lokal" | "anhang"

export interface Sicherung {
  id: number
  art: SicherungArt
  status: "wartet" | "laeuft" | "fertig" | "fehler"
  sha256: string
  bytes: number
  mime: string
  dateiname: string
  fremd_url: string
  abgerufen_von: string
  gesichert_am: string | null
  fehler: string
}

export interface Quelle {
  id: number
  url: string
  titel: string
  herausgeber: string
  veroeffentlicht_am: string | null
  abgerufen_am: string | null
  archiv_url: string
  datei_url: string
  guete: Guete
  notiz: string
  meta?: { titel?: string; herausgeber?: string; beschreibung?: string; bild?: string }
  stand?: { sicherungen: Sicherung[]; vorschau: number | null; fundstellen: { id: number; beleg: number; zitat: string }[] }
}

export interface Beweis {
  id: number
  quelle: number
  quelle_detail: Quelle
  x: number
  y: number
  /** Die Fäden, die es belegt, als [von, nach] */
  faeden: [number, number][]
}

export interface Beleg {
  id?: number
  quelle: number
  quelle_detail?: Quelle
  zitat_woertlich: string
  fundstelle: string
}

export interface Befund {
  code: string
  text: string
}

export interface Verbindung {
  id: number
  von: number
  nach: number
  typ: VerbindungTyp
  beschreibung: string
  start: string | null
  ende: string | null
  aktuell: boolean
  betrag: string | null
  waehrung: string
  aussageart: Aussageart
  // Fehlen in der Lese-Ansicht für Mitglieder (views._mitglied_faden), daher optional.
  konfidenz?: number
  anhoerung_angefragt_am?: string | null
  anhoerung_antwort?: string
  anhoerung_antwort_am?: string | null
  status: Status
  belege: Beleg[]
  befunde: Befund[]
  ausgeblendet?: boolean
}

export interface Board {
  id: number
  titel: string
  slug: string
  beschreibung: string
  look: "dunkel" | "papier"
  oeffentlich?: boolean
  /** false = Mitglied, nur Lesen. */
  darf_bearbeiten?: boolean
  /** Slugs der Wände, auf denen dieses Board als Mappe liegt (der Baum der Akte). */
  eltern?: string[]
}

export interface BoardVerweis {
  slug: string
  titel: string
}

/** Miniatur eines Unter-Boards, alles auf 0..1 gerechnet. */
export interface MappeVorschau {
  seitenverhaeltnis: number
  rahmen: [number, number, number, number, string][]
  karten: [number, number][]
}

export interface MappeGesicht {
  id?: number
  typ: EntitaetTyp
  name: string
  bild_url: string
  bild_nachweis?: string
}

/** Ein anderes Board als Aktenmappe auf dieser Wand (apps/api/akte/mappen.py). */
export interface Mappe {
  id: number
  ziel: string
  titel: string
  beschreibung: string
  x: number
  y: number
  farbe: string
  zaehler: { karten: number; faeden: number; quellen: number }
  gesichter: MappeGesicht[]
  vorschau: MappeVorschau
}

/** Fäden zwischen einer Karte und einer Mappe oder zwischen zwei Mappen, als ein Strang. */
export interface Buendel {
  id: string
  /** Knoten-IDs: "k-<Karte>" oder "m-<Mappe>" */
  von: string
  nach: string
  faeden: number[]
  je_art: Partial<Record<Aussageart, number>>
  je_typ: [VerbindungTyp, number][]
  mit_betrag: number
  /** Werkstatt: auf dieser Wand ausgeblendete Fäden zwischen denselben Enden (zum Wiedereinblenden). */
  ausgeblendet?: number[]
}

/** Eine Karte, die nicht auf dieser Wand liegt, sondern in einer ihrer Mappen. */
export interface EntitaetAussen extends EntitaetKurz {
  /** Knoten-ID der Mappe, in der sie steckt */
  mappe: string
}

export interface Karte {
  id: number
  entitaet: number
  entitaet_detail: EntitaetKurz
  x: number
  y: number
  farbe: string
}

export interface Zettel {
  id: number
  art: "notiz" | "meinung" | "frage"
  text: string
  x: number
  y: number
}

export interface Rahmen {
  id: number
  titel: string
  x: number
  y: number
  breite: number
  hoehe: number
  farbe: string
}

export interface Station {
  position?: number
  x: number
  y: number
  zoom: number
  fokus: number[]
  stichwort: string
  dauer_ms: number
  beweis_quelle?: number | null
  beweis_zitat?: string
  /** Sprechtext der Station (gesichtsloses Video). */
  text?: string
  einblendung?: { gross?: string; klein?: string; quelle?: string; voll?: boolean }
  /** O-Ton-Einspieler (nur Render): lokale Datei, Ausschnitt in Sekunden, Urheberangabe. */
  einspieler?: { datei?: string; ab?: number; bis?: number; quelle?: string; freeze_ms?: number; untertitel?: string }
}

export interface Fahrt {
  id: number
  titel: string
  stationen: Station[]
}

export interface Wand {
  board: Board
  karten: Karte[]
  faeden: Verbindung[]
  zettel: Zettel[]
  rahmen: Rahmen[]
  fahrten: Fahrt[]
  beweise: Beweis[]
  /** false = Mitglied, nur Lesen (Karten, Rahmen, belegte Fäden). */
  darf_bearbeiten?: boolean
  // Mappen (seit Runde 15). Optional, damit eine ältere API die Wand nicht bricht.
  mappen?: Mappe[]
  buendel?: Buendel[]
  buendel_faeden?: Verbindung[]
  ausser_haus?: EntitaetAussen[]
  /** Entität (bzw. Kennung) → andere Wände, auf denen sie liegt */
  auch_in?: Record<string, BoardVerweis[]>
  eltern?: BoardVerweis[]
  /** Karten, die in mehreren Mappen stecken, aber nicht auf dieser Wand liegen */
  gelenke?: EntitaetKurz[]
}

export const TYP_NAMEN: Record<EntitaetTyp, string> = {
  person: "Person", organisation: "Organisation", firma: "Firma", behoerde: "Behörde",
  partei: "Partei", ereignis: "Ereignis", gesetz: "Gesetz / Verfahren", system: "System / Produkt",
  ort: "Ort", dokument: "Dokument",
}

export const VERBINDUNG_NAMEN: Record<VerbindungTyp, string> = {
  amt: "Amt / Position", eigentum: "Eigentum / Beteiligung", finanzierung: "Finanzierung / Zahlung",
  mitgliedschaft: "Mitgliedschaft", auftrag: "Auftrag / Vertrag", lobby: "Lobby / Beratung",
  gesetz_betrifft: "Gesetz betrifft", aussage: "Aussage / Zitat", familie: "Familie", sonstiges: "Sonstiges",
}

export const AUSSAGE_NAMEN: Record<Aussageart, string> = {
  belegt: "Belegt", verdacht: "Verdacht", meinung: "Meinung",
}
