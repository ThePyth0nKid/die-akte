"use client"

// Die Wand: Karten, Fäden, Zettel und Rahmen auf einer unendlichen Leinwand,
// dazu Notiz-Seite, Befehlszeile, Weg-Finden, Fahrten und der Aufnahme-Modus.

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react"
import { flushSync } from "react-dom"
import {
  Background, BackgroundVariant, ConnectionMode, Controls, MiniMap, ReactFlow, ReactFlowProvider,
  useNodesInitialized, useReactFlow, type Connection, type Edge, type Node, type NodeChange, applyNodeChanges,
} from "@xyflow/react"
import {
  ArrowLeft, FolderPlus, Frame, GitMerge, LayoutGrid, MapPin, Paperclip, Route, Search, StickyNote, Video,
} from "lucide-react"
import { akte } from "@/lib/akte/api"
import {
  bildZu, fadenLicht, FORMATE, licht, rahmeStation, rahmeUeberEinblendung, STANDARD, ueberblick, viewportVon, zeitplan,
  type Bild, type FokusKarte, type FormatKennung, type Kamera, type Plan, type PlanEingabe,
} from "@/lib/akte/aufnahme"
import { durchhang, FARBEN, zeitraum } from "@/lib/akte/faden"
import { eintauchKamera, MAPPE_B, MAPPE_H, mappenAdresse, pfadLesen, zurueckAdresse } from "@/lib/akte/mappen"
import {
  etikettBreite, etikettenVersatz, etikettHoehe, freierPlatz, passendeGroesse, type Rechteck,
} from "@/lib/akte/ordnung"
import type {
  Board, BoardVerweis, Buendel, EntitaetKurz, Fahrt, Mappe, Quelle, Station, Verbindung, Wand as WandDaten, Zettel,
} from "@/lib/akte/typen"
import AufnahmeDialog from "./AufnahmeDialog"
import BeweisAnsicht, { bildFuerBeweis } from "./BeweisAnsicht"
import Befehlszeile from "./Befehlszeile"
import Brotkrumen from "./Brotkrumen"
import { BuendelKante, BuendelLeiste } from "./Buendel"
import FadenFormular from "./FadenFormular"
import FahrtenLeiste from "./FahrtenLeiste"
import { kantenTypen } from "./FadenKante"
import { knotenTypen } from "./knoten"
import NotizLeiste from "./NotizLeiste"
import { FadenLesen, KarteLesen } from "./LeseAnsicht"

type Rahmenhilfe = "16:9" | "9:16" | null

/** Farbe je Kartentyp — Minimap und Legende. */
const TYP_FARBE: Record<string, string> = {
  person: "#FF1744", firma: "#f0c674", organisation: "#FFB300", behoerde: "#00E5FF", partei: "#7B3FE4",
  gesetz: "#22E07A", system: "#8A94A0", ereignis: "#F2F7FB", ort: "#10B981", dokument: "#EDE6D8",
}

const GROESSE: Record<string, { b: number; h: number }> = {
  karte: { b: 220, h: 380 }, zettel: { b: 200, h: 200 }, beweis: { b: 220, h: 300 }, mappe: { b: MAPPE_B, h: MAPPE_H },
}
const ART_JE_PRAEFIX: Record<string, string> = { k: "karte", z: "zettel", r: "rahmen", b: "beweis", m: "mappe" }
const alleKantenTypen = { ...kantenTypen, buendel: BuendelKante }

/** Woher man kam: `?von=` (Weg), `?karte=` (Portal-Sprung), `?aus=` (eine Ebene zurück). */
export interface Ankunft {
  von?: string
  karte?: string
  aus?: string
}

function rechteckVon(n: Node): Rechteck | null {
  if (n.type === "rahmen") return null
  const g = GROESSE[n.type ?? "karte"] ?? GROESSE.karte
  return { x: n.position.x, y: n.position.y, b: n.measured?.width ?? g.b, h: n.measured?.height ?? g.h }
}
type FadenDialog = { von: EntitaetKurz; nach: EntitaetKurz; vorhanden?: Verbindung }

const bewegungArm = () =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches

/** Gerenderte Aufnahme: das Bild ist eine reine Funktion der Zeit (`window.__akteRender`). */
export interface RenderAuftrag {
  fahrtId: number
  format: FormatKennung
  look?: "dunkel" | "papier"
  stichworte: boolean
  legende: boolean
  halteMs: number
  /** Deckkraft außerhalb des Fokus (Vorgabe 0,12; im Video 0,04 plus Unschärfe, damit nichts Fremdes lesbar ist). */
  dimm?: number
  /** Fadenetiketten zeichnen (Vorgabe ja). */
  etiketten?: boolean
  /** Entitäten, deren Karten samt Fäden im Render fehlen (z. B. Opfer: nie in ein Video, auch nicht abgedunkelt). */
  ohne?: number[]
  /** So viele Pixel unter den Fokus-Karten frei lassen (Zählwerk unten im Schnitt). */
  freiUnten?: number
}

/** Render: Karten aus `ohne` samt ihrer Fäden und Belegen weglassen. */
function ohneFiltern<T extends WandDaten>(w: T, ohne: number[] | undefined): T {
  if (!ohne?.length) return w
  const weg = new Set(ohne)
  // Auch über Namen: Mappen-Gesichter ohne ID und Zettel tragen nur den Namen (Review 06.10.2026)
  // voller Name und Nachname (≥ 5 Zeichen): „Berger v. Graf“ in einem Quellentitel nennt die Person auch
  const namen = w.karten.filter((k) => weg.has(k.entitaet))
    .flatMap((k) => { const n = k.entitaet_detail.name.toLowerCase(); return [n, n.split(/\s+/).pop() ?? ""] })
    .filter((n) => n.length >= 5)
  const nennt = (text: string) => namen.some((n) => text.toLowerCase().includes(n))
  const fadenWeg = new Set([...(w.faeden ?? []), ...(w.buendel_faeden ?? [])]
    .filter((f) => weg.has(f.von) || weg.has(f.nach)).map((f) => f.id))
  return {
    ...w,
    karten: w.karten.filter((k) => !weg.has(k.entitaet)),
    faeden: w.faeden.filter((f) => !weg.has(f.von) && !weg.has(f.nach)),
    // Ein Beweis, der nur Fäden der weggelassenen Karte belegt, verschwindet mit ihr (sein Titel kann den Namen tragen)
    beweise: w.beweise
      .map((b) => ({ ...b, faedenVorher: b.faeden.length, faeden: b.faeden.filter(([v, n]) => !weg.has(v) && !weg.has(n)) }))
      .filter((b) => !(b.faedenVorher > 0 && b.faeden.length === 0) && !nennt(b.quelle_detail?.titel ?? ""))
      .map(({ faedenVorher: _, ...b }) => b),
    buendel: w.buendel
      ?.map((bu) => ({ ...bu, faeden: bu.faeden.filter((id) => !fadenWeg.has(id)) }))
      .filter((bu) => bu.faeden.length > 0),
    mappen: w.mappen?.map((m) => ({
      ...m, gesichter: (m.gesichter ?? []).filter((g) => !(g.id !== undefined && weg.has(g.id)) && !nennt(g.name)),
    })),
    zettel: w.zettel.filter((z) => !nennt(z.text ?? "")),
  }
}

/** Schnittstelle für den Renderer (scripts/akte/render_fahrt.cjs). */
export interface AkteRender {
  bereit: () => Promise<{
    dauerMs: number; getaktet: boolean; fehlendeBilder: string[]
    /** Einspieler, die der Renderer vorab in Einzelbilder zerlegt (…/__einspieler/<station>/<nr>.jpg). */
    einspieler: { station: number; datei: string; ab: number; bis: number }[]
    stationen: {
      start: number; ankunft: number; standbild: number; stichwort: string; kameras: Kamera[]
      einspieler: { t0: number; laufBis: number } | null
    }[]
  }>
  setzeZeit: (ms: number) => Promise<void>
}

declare global {
  interface Window {
    __akteRender?: AkteRender
    /** Satzanfänge je Station und Länge der Tonspur (ms), vom Renderer vor dem Laden gesetzt. */
    __akteZeiten?: { stationen: number[]; ende_ms: number; anfaenge?: string[] }
  }
}

const naechstesBild = () => new Promise<void>((fertig) => requestAnimationFrame(() => fertig()))

const dekodiert = new WeakSet<HTMLImageElement>()

/**
 * Wartet, bis jedes Bild im Dokument geladen und dekodiert ist — kein halbes Bild im Video.
 * Schon dekodierte Bilder werden nicht erneut geprüft (bei 1000+ Bildern je Fahrt spürbar).
 */
async function bilderFertig() {
  await Promise.all([...document.images].map(async (img) => {
    if (dekodiert.has(img) && img.complete) return
    if (!img.complete) await new Promise((fertig) => { img.addEventListener("load", fertig, { once: true }); img.addEventListener("error", fertig, { once: true }) })
    await img.decode().then(() => dekodiert.add(img)).catch(() => undefined)
  }))
}

// Der Rechnername ändert sich nicht: kein Abo nötig.
const nieAendern = () => () => undefined

export default function Wand({ slug, render, ankunft }: { slug: string; render?: RenderAuftrag; ankunft?: Ankunft }) {
  return (
    <ReactFlowProvider>
      <WandInnen slug={slug} render={render} ankunft={ankunft} />
    </ReactFlowProvider>
  )
}

function WandInnen({ slug, render, ankunft }: { slug: string; render?: RenderAuftrag; ankunft?: Ankunft }) {
  const flow = useReactFlow()
  const router = useRouter()
  const [buendelOffen, setBuendelOffen] = useState<string | null>(null)
  const [tauchen, setTauchen] = useState(false)
  const [boardsListe, setBoardsListe] = useState<Board[] | null>(null)
  const [wand, setWand] = useState<WandDaten | null>(null)
  const [fehler, setFehler] = useState("")
  const [auswahl, setAuswahl] = useState<number | null>(null)
  const [fadenDialog, setFadenDialog] = useState<FadenDialog | null>(null)
  const [befehl, setBefehl] = useState(false)
  const [aufnahme, setAufnahme] = useState(!!render)
  const [rahmenhilfe, setRahmenhilfe] = useState<Rahmenhilfe>(null)
  const [fokus, setFokus] = useState<Set<number> | null>(null)
  const [fahrtenOffen, setFahrtenOffen] = useState(false)
  const [fahrtId, setFahrtId] = useState<number | null>(null)
  const [stationIndex, setStationIndex] = useState(-1)
  const [meldung, setMeldung] = useState("")
  const [lokal, setLokal] = useState<Record<string, Partial<Node>>>({})
  const [legende, setLegende] = useState(render ? render.legende : true)
  const [stichwortZeigen, setStichwortZeigen] = useState(false)
  const [aufnahmeDialog, setAufnahmeDialog] = useState(false)
  const [renderBild, setRenderBild] = useState<Bild | null>(null)
  const [renderQuellen, setRenderQuellen] = useState<Map<number, Quelle>>(() => new Map())
  const vorgeladen = useRef<HTMLImageElement[]>([])
  const [ziehtDatei, setZiehtDatei] = useState(false)
  const [beweisAnsicht, setBeweisAnsicht] = useState<{ quelle: Quelle; zitat?: string } | null>(null)
  const [fadenLesen, setFadenLesen] = useState<Verbindung | null>(null)
  // Aufnahme und Fahrten brauchen den eigenen Rechner (lokaler Render-Dienst 8178, lokale Einspieler).
  const amRechner = useSyncExternalStore(nieAendern, () => ["127.0.0.1", "localhost"].includes(window.location.hostname), () => false)
  // Jede neue Station (oder Esc) macht ältere, noch laufende Beweis-Zeitgeber ungültig.
  const beweisRunde = useRef(0)
  const dateiWahl = useRef<HTMLInputElement>(null)
  const ausstehend = useRef(new Map<string, { art: string; id: number; x: number; y: number; breite?: number; hoehe?: number }>())
  const speicherTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const laden = useCallback(async () => {
    try {
      setWand(ohneFiltern(await akte.wand(slug), render?.ohne))
      // Frische Serverdaten gewinnen; lokal bleiben nur Auswahl und Messung.
      setLokal((alt) => Object.fromEntries(
        Object.entries(alt).map(([id, n]) => [id, { selected: n.selected, measured: n.measured }]),
      ))
    } catch {
      setFehler("Das Board konnte nicht geladen werden. Es ist nicht freigegeben, oder du bist nicht angemeldet.")
    }
  }, [slug, render?.ohne])

  useEffect(() => {
    let aktiv = true
    akte.wand(slug)
      .then((w) => { if (aktiv) setWand(ohneFiltern(w, render?.ohne)) })
      .catch(() => { if (aktiv) setFehler("Das Board konnte nicht geladen werden. Es ist nicht freigegeben, oder du bist nicht angemeldet.") })
    return () => { aktiv = false }
  }, [slug, render?.ohne])

  const melden = useCallback((text: string) => {
    setMeldung(text)
    setTimeout(() => setMeldung(""), 3500)
  }, [])

  // Board-Liste für Brotkrumen-Titel und die Mappen-Wahl (im Render nicht nötig).
  useEffect(() => {
    if (render) return
    let aktiv = true
    akte.boards().then((b) => { if (aktiv) setBoardsListe(b) }).catch(() => undefined)
    return () => { aktiv = false }
  }, [render])

  // ─── Mappen: der Weg hierher, hinein und hinaus ──────────────────────────
  const pfad = useMemo(() => pfadLesen(ankunft?.von, wand?.eltern ?? [], slug), [ankunft?.von, wand?.eltern, slug])
  const titelJe = useMemo(() => {
    const m = new Map<string, string>()
    for (const b of boardsListe ?? []) m.set(b.slug, b.titel)
    for (const e of wand?.eltern ?? []) m.set(e.slug, e.titel)
    return m
  }, [boardsListe, wand?.eltern])

  // Ein Eintauchen auf einmal; der Zeitgeber stirbt mit der Wand (kein zweites router.push auf eine verlassene Wand).
  const tauchZeit = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => () => { if (tauchZeit.current) clearTimeout(tauchZeit.current) }, [])
  const eintauchen = useCallback((m: Mappe) => {
    if (render || tauchZeit.current) return
    const ziel = mappenAdresse(m.ziel, pfad, slug)
    if (bewegungArm()) { router.push(ziel); return }
    const flaeche = document.querySelector(".react-flow")?.getBoundingClientRect()
    const k = eintauchKamera({ x: m.x, y: m.y, b: MAPPE_B, h: MAPPE_H }, { b: flaeche?.width ?? 1200, h: flaeche?.height ?? 800 })
    flow.setCenter(k.x, k.y, { zoom: k.zoom, duration: 480 })
    setTauchen(true)
    tauchZeit.current = setTimeout(() => router.push(ziel), 430)
  }, [render, pfad, slug, flow, router])

  const hinauf = useCallback(() => {
    const ziel = zurueckAdresse(pfad, slug)
    if (ziel) router.push(ziel)
  }, [pfad, slug, router])

  // ─── Positionen gesammelt speichern ──────────────────────────────────────
  const merkePosition = useCallback((eintrag: { art: string; id: number; x: number; y: number; breite?: number; hoehe?: number }) => {
    ausstehend.current.set(`${eintrag.art}-${eintrag.id}`, { ...ausstehend.current.get(`${eintrag.art}-${eintrag.id}`), ...eintrag })
    if (speicherTimer.current) clearTimeout(speicherTimer.current)
    speicherTimer.current = setTimeout(() => {
      const liste = [...ausstehend.current.values()]
      ausstehend.current.clear()
      akte.positionen(slug, liste).catch(() => melden("Positionen nicht gespeichert."))
    }, 400)
  }, [slug, melden])

  const zettelSpeichern = useCallback((z: Zettel, text: string) => {
    akte.zettelAendern(slug, z.id, { text })
      .then((neu) => setWand((w) => w && { ...w, zettel: w.zettel.map((x) => (x.id === neu.id ? neu : x)) }))
      .catch(() => melden("Zettel nicht gespeichert."))
  }, [slug, melden])

  // ─── Knoten und Fäden aus den Daten bauen ─────────────────────────────────
  const karteZuEntitaet = useMemo(() => new Map(wand?.karten.map((k) => [`k-${k.id}`, k.entitaet_detail]) ?? []), [wand])
  const entitaetZuKnoten = useMemo(() => new Map(wand?.karten.map((k) => [k.entitaet, `k-${k.id}`]) ?? []), [wand])
  const namenJe = useMemo(() => new Map(wand?.karten.map((k) => [k.entitaet, k.entitaet_detail]) ?? []), [wand])
  // Auch die Karten in den Mappen (für Bündel-Fäden): wer nicht auf dieser Wand liegt, steht in ausser_haus.
  const alleNamen = useMemo(() => {
    const m = new Map<number, EntitaetKurz>(namenJe)
    for (const e of wand?.ausser_haus ?? []) if (!m.has(e.id)) m.set(e.id, e)
    return m
  }, [namenJe, wand?.ausser_haus])
  const papier = (render?.look ?? wand?.board.look) === "papier"
  // Mitglieder lesen nur: nichts ziehen, verbinden, löschen oder anlegen.
  const nurLesen = wand?.darf_bearbeiten === false
  const gesperrt = aufnahme || nurLesen

  // Die Knoten folgen den Daten (useMemo); was der Nutzer gerade tut — ziehen,
  // wählen, Größe ändern — liegt als Überlagerung darüber. So braucht es keinen
  // Effekt, der Zustand aus Zustand nachbaut.
  const basisKnoten = useMemo((): Node[] => {
    if (!wand) return []
    const befundeJe = new Map<number, number>()
    for (const f of wand.faeden) {
      if (!f.befunde.length) continue
      befundeJe.set(f.von, (befundeJe.get(f.von) ?? 0) + 1)
      befundeJe.set(f.nach, (befundeJe.get(f.nach) ?? 0) + 1)
    }
    const gedimmt = (id: number) => !!fokus && !fokus.has(id)
    // Render-Modus: Helligkeit aus der Zeit (Scheinwerfer blendet über), nicht aus CSS-Übergängen.
    const rb = renderBild
    const hell = (id: number) => (rb ? licht(rb.fokus, id) : 1)
    const allesHell = hell(-1)
    // Abdunkeln außerhalb des Fokus; im Video mit Unschärfe, damit keine fremde Karte lesbar bleibt (sonst ist eine fremde Karte im Video lesbar)
    const dimm = render?.dimm ?? 0.12
    const deck = (h: number) => dimm + (1 - dimm) * h
    const rahmenMin = render?.dimm === undefined ? 0.25 : Math.min(0.25, 2 * render.dimm)
    const unscharf = (h: number) => (rb && render?.dimm !== undefined && h < 0.999 ? { filter: `blur(${((1 - h) * 6).toFixed(2)}px)` } : undefined)
    return [
      ...wand.rahmen.map((r): Node => ({
        id: `r-${r.id}`, type: "rahmen", position: { x: r.x, y: r.y }, zIndex: -1,
        style: { width: r.breite, height: r.hoehe },
        draggable: !gesperrt, selectable: !gesperrt,
        data: {
          titel: r.titel, farbe: r.farbe, aufnahme: gesperrt, gedimmt: !!fokus,
          deckkraft: rb ? rahmenMin + (1 - rahmenMin) * allesHell : undefined,
          groesse: (x: number, y: number, breite: number, hoehe: number) => {
            merkePosition({ art: "rahmen", id: r.id, x, y, breite, hoehe })
            setWand((w) => w && { ...w, rahmen: w.rahmen.map((a) => (a.id === r.id ? { ...a, x, y, breite, hoehe } : a)) })
          },
        },
      })),
      ...wand.karten.map((k): Node => ({
        id: `k-${k.id}`, type: "karte", position: { x: k.x, y: k.y },
        draggable: !gesperrt, connectable: !gesperrt, style: unscharf(hell(k.entitaet)),
        data: {
          entitaet: k.entitaet_detail, befunde: befundeJe.get(k.entitaet) ?? 0, gedimmt: gedimmt(k.entitaet), aufnahme, papier, nurLesen,
          deckkraft: rb ? deck(hell(k.entitaet)) : undefined,
          auchIn: wand.auch_in?.[String(k.entitaet)],
          springen: (ziel: string) => {
            const q = new URLSearchParams({ karte: k.entitaet_detail.slug })
            router.push(`/akte/${ziel}?${q.toString()}`)
          },
        },
      })),
      ...(wand.mappen ?? []).map((m): Node => ({
        id: `m-${m.id}`, type: "mappe", position: { x: m.x, y: m.y },
        draggable: !gesperrt, connectable: false, style: unscharf(allesHell),
        data: {
          mappe: m, gedimmt: !!fokus, aufnahme, papier, oeffnen: () => eintauchen(m),
          deckkraft: rb ? deck(allesHell) : undefined,
        },
      })),
      ...wand.beweise.map((b): Node => ({
        id: `b-${b.id}`, type: "beweis", position: { x: b.x, y: b.y },
        draggable: !gesperrt, connectable: false, style: unscharf(Math.max(allesHell, ...b.faeden.flat().map(hell))),
        data: {
          quelle: b.quelle_detail, aufnahme,
          gedimmt: !!fokus && !b.faeden.some(([v, n]) => fokus.has(v) || fokus.has(n)),
          deckkraft: rb ? deck(Math.max(allesHell, ...b.faeden.flat().map(hell))) : undefined,
        },
      })),
      ...wand.zettel.map((z): Node => ({
        id: `z-${z.id}`, type: "zettel", position: { x: z.x, y: z.y },
        draggable: !gesperrt, connectable: false, style: unscharf(allesHell),
        data: {
          zettel: z, gedimmt: !!fokus, aufnahme: gesperrt, speichern: (text: string) => zettelSpeichern(z, text),
          deckkraft: rb ? deck(allesHell) : undefined,
        },
      })),
    ]
  }, [wand, fokus, aufnahme, gesperrt, nurLesen, papier, merkePosition, zettelSpeichern, renderBild, router, eintauchen, render?.dimm])

  const knoten = useMemo(
    (): Node[] => basisKnoten.map((n) => (lokal[n.id] ? { ...n, ...lokal[n.id] } : n)),
    [basisKnoten, lokal],
  )

  // Beschriftungen weichen einander aus: Mitte jedes Fadens ausrechnen, dann entzerren.
  // Aus den gespeicherten Positionen, nicht aus jedem Zieh-Bild: sonst springen beim Ziehen
  // einer Karte die Beschriftungen ganz anderer Fäden, und die Rechnung läuft 60-mal je Sekunde.
  // Die gerenderte Aufnahme nimmt dieselben Rechtecke mit in den Bildrahmen.
  const etikettLage = useMemo(() => {
    const sichtbar = (wand?.faeden ?? []).filter(
      (f) => !f.ausgeblendet && entitaetZuKnoten.has(f.von) && entitaetZuKnoten.has(f.nach),
    )
    const lage = new Map(wand?.karten.map((k) => [`k-${k.id}`, { x: k.x + 110, y: k.y }]) ?? [])
    for (const m of wand?.mappen ?? []) lage.set(`m-${m.id}`, { x: m.x + MAPPE_B / 2, y: m.y })
    const etiketten = sichtbar.flatMap((f) => {
      const a = lage.get(entitaetZuKnoten.get(f.von)!)
      const b = lage.get(entitaetZuKnoten.get(f.nach)!)
      if (!a || !b || !f.beschreibung) return []
      const { mitteX, mitteY } = durchhang(a.x, a.y, b.x, b.y)
      const text = `${f.beschreibung} ${zeitraum(f, f.beschreibung)}`
      return [{ id: `f-${f.id}`, von: f.von, nach: f.nach, x: mitteX, y: mitteY, b: etikettBreite(text), h: etikettHoehe(text, f.aussageart !== "belegt") }]
    })
    // Bündel-Aufschriften weichen genauso aus; von/nach = -1: sie gehören nie zum Beiwerk einer Station.
    for (const bu of wand?.buendel ?? []) {
      const a = lage.get(bu.von)
      const b = lage.get(bu.nach)
      if (!a || !b) continue
      const { mitteX, mitteY } = durchhang(a.x, a.y, b.x, b.y)
      const einzeln = bu.faeden.length === 1
      etiketten.push({ id: `bu-${bu.id}`, von: -1, nach: -1, x: mitteX, y: mitteY, b: einzeln ? 170 : 220, h: einzeln ? 26 : 64 })
    }
    const g = (art: string) => GROESSE[art]
    // Portal-Reiter („auch in …“) hängen unter der Karte: sie zählen mit, damit keine Aufschrift sie verdeckt —
    // aber nur, wenn sie gezeichnet werden (nicht in Aufnahme und Render, sonst weicht das Bild von der Wand ab).
    const reiter = (k: { entitaet: number }) => (aufnahme ? 0 : Math.min(4, wand?.auch_in?.[String(k.entitaet)]?.length ?? 0))
    const hindernisse: Rechteck[] = [
      ...(wand?.karten.map((k) => (reiter(k)
        ? { x: k.x, y: k.y, b: 260, h: g("karte").h + 12 + 26 * reiter(k) }
        : { x: k.x, y: k.y, ...g("karte") })) ?? []),
      ...(wand?.zettel.map((z) => ({ x: z.x, y: z.y, ...g("zettel") })) ?? []),
      ...(wand?.beweise.map((b) => ({ x: b.x, y: b.y, ...g("beweis") })) ?? []),
      ...(wand?.mappen?.map((m) => ({ x: m.x, y: m.y, ...g("mappe") })) ?? []),
    ]
    const versatz = etikettenVersatz(etiketten, 4, hindernisse)
    return { sichtbar, etiketten, versatz }
  }, [wand, entitaetZuKnoten, aufnahme])

  const kanten = useMemo((): Edge[] => {
    if (!wand) return []
    const { sichtbar, versatz } = etikettLage
    // Beweisstück → die Karten der Fäden, die es belegt (dünn, gold, gestrichelt).
    const belegKanten: Edge[] = wand.beweise.flatMap((b) => {
      const ziele = new Set(b.faeden.flat().filter((id) => entitaetZuKnoten.has(id)))
      return [...ziele].map((id) => ({
        id: `bl-${b.id}-${id}`, source: `b-${b.id}`, target: entitaetZuKnoten.get(id)!,
        sourceHandle: "nadel", targetHandle: "nadel", selectable: false, focusable: false,
        style: {
          stroke: FARBEN.gold, strokeWidth: 1.5, strokeDasharray: "3 6",
          opacity: renderBild ? Math.min(0.06, render?.dimm ?? 0.06) + 0.49 * licht(renderBild.fokus, id) : fokus && !fokus.has(id) ? 0.06 : 0.55,
        },
      }))
    })
    const knotenIds = new Set([...wand.karten.map((k) => `k-${k.id}`), ...(wand.mappen ?? []).map((m) => `m-${m.id}`)])
    const allesHell = renderBild ? licht(renderBild.fokus, -1) : 1
    const buendelKanten: Edge[] = (wand.buendel ?? [])
      .filter((bu) => knotenIds.has(bu.von) && knotenIds.has(bu.nach))
      .map((bu) => ({
        id: `bu-${bu.id}`, type: "buendel", source: bu.von, target: bu.nach,
        sourceHandle: "nadel", targetHandle: "nadel", selectable: !aufnahme,
        data: {
          buendel: bu, aufnahme, papier, gedimmt: !!fokus,
          versatz: versatz.get(`bu-${bu.id}`) ?? 0,
          render: renderBild ? { hell: allesHell } : undefined,
          oeffnen: aufnahme ? undefined : () => { setAuswahl(null); setBuendelOffen(bu.id) },
        },
      }))
    return [...belegKanten, ...buendelKanten, ...sichtbar.map((f) => ({
      id: `f-${f.id}`, type: "faden",
      source: entitaetZuKnoten.get(f.von)!, target: entitaetZuKnoten.get(f.nach)!,
      sourceHandle: "nadel", targetHandle: "nadel",
      selectable: !aufnahme,
      data: {
        verbindung: f, aufnahme, papier,
        gedimmt: !!fokus && !(fokus.has(f.von) && fokus.has(f.nach)),
        hervorgehoben: !!fokus && fokus.has(f.von) && fokus.has(f.nach),
        versatz: versatz.get(`f-${f.id}`) ?? 0,
        render: renderBild ? { ...fadenRender(renderBild, f.von, f.nach), dimm: render?.dimm, etikett: render?.etiketten !== false } : undefined,
      },
    }))]
  }, [wand, entitaetZuKnoten, etikettLage, fokus, aufnahme, papier, renderBild, render?.dimm, render?.etiketten])

  // Nur die Knoten, die React Flow gerade verändert, wandern in die Überlagerung.
  const onNodesChange = useCallback((changes: NodeChange[]) => {
    const betroffen = new Set(changes.map((c) => ("id" in c ? c.id : "")).filter(Boolean))
    const danach = applyNodeChanges(changes, knoten)
    setLokal((alt) => {
      const neu = { ...alt }
      for (const n of danach) {
        if (!betroffen.has(n.id)) continue
        neu[n.id] = {
          position: n.position, selected: n.selected, dragging: n.dragging, measured: n.measured,
          width: n.width, height: n.height,
        }
      }
      return neu
    })
  }, [knoten])

  const onNodeDragStop = useCallback((_: unknown, __: Node, gezogenRoh: Node[]) => {
    const ids = new Set(gezogenRoh.map((n) => n.id))
    const andere = knoten.filter((n) => !ids.has(n.id)).map(rechteckVon).filter((r): r is Rechteck => !!r)
    const gezogen = gezogenRoh.map((n) => {
      const r = rechteckVon(n)
      if (!r) return n
      const platz = freierPlatz(r, andere)
      andere.push({ ...r, ...platz })
      return platz.x === n.position.x && platz.y === n.position.y ? n : { ...n, position: platz }
    })
    setLokal((alt) => {
      const neu = { ...alt }
      for (const n of gezogen) neu[n.id] = { ...neu[n.id], position: n.position, dragging: false }
      return neu
    })
    for (const n of gezogen) {
      const [art, id] = n.id.split("-")
      const name = ART_JE_PRAEFIX[art] ?? "rahmen"
      merkePosition({ art: name, id: Number(id), x: n.position.x, y: n.position.y })
    }
    setWand((w) => {
      if (!w) return w
      const pos = new Map(gezogen.map((n) => [n.id, n.position]))
      return {
        ...w,
        karten: w.karten.map((k) => (pos.has(`k-${k.id}`) ? { ...k, ...pos.get(`k-${k.id}`)! } : k)),
        zettel: w.zettel.map((z) => (pos.has(`z-${z.id}`) ? { ...z, ...pos.get(`z-${z.id}`)! } : z)),
        rahmen: w.rahmen.map((r) => (pos.has(`r-${r.id}`) ? { ...r, ...pos.get(`r-${r.id}`)! } : r)),
        beweise: w.beweise.map((b) => (pos.has(`b-${b.id}`) ? { ...b, ...pos.get(`b-${b.id}`)! } : b)),
        mappen: w.mappen?.map((m) => (pos.has(`m-${m.id}`) ? { ...m, ...pos.get(`m-${m.id}`)! } : m)),
      }
    })
  }, [merkePosition, knoten])

  const aufraeumen = useCallback(async () => {
    try {
      const neu = await akte.aufraeumen(slug)
      setWand(neu)
      setLokal((alt) => Object.fromEntries(
        Object.entries(alt).map(([id, n]) => [id, { selected: n.selected, measured: n.measured }]),
      ))
      setTimeout(() => flow.fitView({ duration: bewegungArm() ? 0 : 700, padding: 0.08 }), 60)
      melden("Aufgeräumt: nichts liegt mehr übereinander.")
    } catch {
      melden("Aufräumen fehlgeschlagen.")
    }
  }, [slug, flow, melden])

  // ─── Faden ziehen und öffnen ──────────────────────────────────────────────
  const onConnect = useCallback((c: Connection) => {
    const von = karteZuEntitaet.get(c.source)
    const nach = karteZuEntitaet.get(c.target)
    if (von && nach && von.id !== nach.id) setFadenDialog({ von, nach })
  }, [karteZuEntitaet])

  const fadenOeffnen = useCallback((v: Verbindung) => {
    const platzhalter = (id: number): EntitaetKurz =>
      alleNamen.get(id) ?? { id, name: `#${id}`, typ: "person", slug: "", kurzbeschreibung: "", bild_url: "", oeffentliche_person: false, status: "entwurf" }
    setFadenDialog({ von: platzhalter(v.von), nach: platzhalter(v.nach), vorhanden: v })
  }, [alleNamen])

  // ─── Karten holen, Links folgen ───────────────────────────────────────────
  const mitte = useCallback(() => {
    const flaeche = document.querySelector(".react-flow")?.getBoundingClientRect()
    if (!flaeche) return { x: 0, y: 0 }
    return flow.screenToFlowPosition({ x: flaeche.left + flaeche.width / 2, y: flaeche.top + flaeche.height / 2 })
  }, [flow])

  const karteHolen = useCallback(async (e: EntitaetKurz, position?: { x: number; y: number }) => {
    setBefehl(false)
    const vorhanden = wand?.karten.find((k) => k.entitaet === e.id)
    if (vorhanden) {
      flow.setCenter(vorhanden.x + 110, vorhanden.y + 150, { zoom: 1, duration: bewegungArm() ? 0 : 600 })
      setAuswahl(e.id)
      return
    }
    const p = position ?? mitte()
    try {
      await akte.karteLegen(slug, e.id, p.x - 110, p.y - 150)
      await laden()
      setAuswahl(e.id)
    } catch {
      melden("Karte konnte nicht aufs Board.")
    }
  }, [wand, flow, mitte, slug, laden, melden])

  const linkFolgen = useCallback(async (name: string) => {
    const treffer = (await akte.suchen(name)).find((t) => t.name.toLowerCase() === name.toLowerCase())
    if (treffer) karteHolen(treffer)
    else melden(`„${name}“ gibt es noch nicht. Über Strg+K anlegen.`)
  }, [karteHolen, melden])

  // ─── Weg finden zwischen zwei gewählten Karten ────────────────────────────
  const wegFinden = useCallback(async () => {
    const gewaehlt = knoten.filter((n) => n.selected && n.type === "karte").map((n) => karteZuEntitaet.get(n.id)!)
    if (gewaehlt.length !== 2) { melden("Genau zwei Karten wählen (Umschalt + Klick)."); return }
    const [a, b] = gewaehlt
    const weg = await akte.weg(a.id, b.id, false)
    if (!weg.gefunden) { melden(`Kein Weg von ${a.name} zu ${b.name} (bis 4 Ecken).`); return }
    const fehlen = weg.entitaeten.filter((id) => !entitaetZuKnoten.has(id))
    if (fehlen.length) {
      const ka = wand!.karten.find((k) => k.entitaet === a.id)!
      const kb = wand!.karten.find((k) => k.entitaet === b.id)!
      await Promise.all(fehlen.map((id, i) => {
        const t = (i + 1) / (fehlen.length + 1)
        return akte.karteLegen(slug, id, ka.x + (kb.x - ka.x) * t, ka.y + (kb.y - ka.y) * t + 260)
      }))
      await laden()
      melden(`${fehlen.length} Karte(n) für den Weg dazugeholt.`)
    }
    setFokus(new Set(weg.entitaeten))
  }, [knoten, karteZuEntitaet, entitaetZuKnoten, wand, slug, laden, melden])

  // ─── Zettel und Rahmen ────────────────────────────────────────────────────
  const zettelNeu = useCallback(async (art: Zettel["art"]) => {
    const p = mitte()
    await akte.zettelAnlegen(slug, { art, text: "", x: p.x - 100, y: p.y - 60 })
    laden()
  }, [mitte, slug, laden])

  const rahmenNeu = useCallback(async (titel: string) => {
    const p = mitte()
    await akte.rahmenAnlegen(slug, { titel, x: p.x - 400, y: p.y - 300, breite: 800, hoehe: 600 })
    laden()
  }, [mitte, slug, laden])

  const mappeNeu = useCallback(async (ziel: string) => {
    const p = mitte()
    const belegt = knoten.map(rechteckVon).filter((r): r is Rechteck => !!r)
    const platz = freierPlatz({ x: p.x - MAPPE_B / 2, y: p.y - MAPPE_H / 2, b: MAPPE_B, h: MAPPE_H }, belegt)
    try {
      await akte.mappeLegen(slug, ziel, platz.x, platz.y)
      await laden()
    } catch (e) {
      melden(e instanceof Error ? e.message : "Mappe konnte nicht auf die Wand.")
    }
  }, [mitte, knoten, slug, laden, melden])

  const gelenkeHolen = useCallback(async () => {
    const liste = wand?.gelenke ?? []
    if (!liste.length) return
    const p = mitte()
    // Jede Karte sucht sich einen freien Platz; die übrige Wand bleibt, wie die Redaktion sie gelegt hat.
    const belegt = knoten.map(rechteckVon).filter((r): r is Rechteck => !!r)
    const ergebnis = await Promise.allSettled(liste.map((g, i) => {
      const platz = freierPlatz({ x: p.x + (i % 6) * 340, y: p.y + Math.floor(i / 6) * 530, b: 220, h: 380 }, belegt)
      belegt.push({ ...platz, b: 220, h: 380 })
      return akte.karteLegen(slug, g.id, platz.x, platz.y)
    }))
    await laden()
    const fehler = ergebnis.filter((r) => r.status === "rejected").length
    melden(fehler
      ? `${liste.length - fehler} von ${liste.length} Gelenken geholt, ${fehler} nicht.`
      : `${liste.length} Gelenk(e) auf die Wand geholt: jetzt sieht man ihre Bündel in jede Mappe.`)
  }, [wand?.gelenke, mitte, knoten, slug, laden, melden])

  const onNodesDelete = useCallback(async (geloescht: Node[]) => {
    try {
      for (const n of geloescht) {
        const [art, id] = n.id.split("-")
        if (art === "k") await akte.karteEntfernen(slug, Number(id))
        if (art === "z") await akte.zettelEntfernen(slug, Number(id))
        if (art === "r") await akte.rahmenEntfernen(slug, Number(id))
        if (art === "b") await akte.beweisEntfernen(slug, Number(id))
        if (art === "m") await akte.mappeEntfernen(slug, Number(id))
      }
    } catch {
      melden("Entfernen fehlgeschlagen.")
    }
    laden()
  }, [slug, laden, melden])

  // Entf auf einem Faden löscht ihn nicht aus der Akte, er wird nur auf diesem Board ausgeblendet.
  const onEdgesDelete = useCallback(async (geloeschtAlle: Edge[]) => {
    const geloescht = geloeschtAlle.filter((e) => e.id.startsWith("f-"))
    if (!geloescht.length) return
    try {
      for (const e of geloescht) await akte.fadenAusblenden(slug, Number(e.id.slice(2)))
      melden("Faden auf diesem Board ausgeblendet. Er bleibt in der Akte.")
    } catch {
      melden("Ausblenden fehlgeschlagen.")
    }
    laden()
  }, [slug, laden, melden])

  // ─── Dateien auf die Wand ziehen → gesichertes Beweisstück ────────────────
  const dateienSichern = useCallback(async (dateien: File[], p: { x: number; y: number }) => {
    if (!dateien.length) return
    const belegt = knoten.map(rechteckVon).filter((r): r is Rechteck => !!r)
    let fehler = 0
    for (const [i, datei] of dateien.entries()) {
      // Neue Beweisstücke suchen sich einen freien Platz, statt auf einer Karte zu landen.
      const platz = freierPlatz({ x: p.x - 110 + i * 260, y: p.y - 150, b: 220, h: 300 }, belegt)
      belegt.push({ ...platz, b: 220, h: 300 })
      try {
        await akte.quelleAusDatei(datei, { board: slug, x: platz.x, y: platz.y })
      } catch {
        fehler++
      }
    }
    await laden()
    melden(fehler ? `${fehler} Datei(en) abgelehnt: nur PDF oder Bild, höchstens 15 MB.` : `${dateien.length} Beweisstück(e) gesichert.`)
  }, [slug, laden, melden, knoten])

  const dateienAblegen = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setZiehtDatei(false)
    dateienSichern([...e.dataTransfer.files], flow.screenToFlowPosition({ x: e.clientX, y: e.clientY }))
  }, [dateienSichern, flow])

  const quelleAnDieWand = useCallback(async (quelleId: number) => {
    const p = mitte()
    const belegt = knoten.map(rechteckVon).filter((r): r is Rechteck => !!r)
    const platz = freierPlatz({ x: p.x - 110, y: p.y - 150, b: 220, h: 300 }, belegt)
    try {
      await akte.beweisLegen(slug, quelleId, platz.x, platz.y)
      await laden()
    } catch {
      melden("Beweisstück konnte nicht an die Wand.")
    }
  }, [mitte, slug, laden, melden, knoten])

  // ─── Fahrten: Stationen anfahren ──────────────────────────────────────────
  const fahrt: Fahrt | undefined = wand?.fahrten.find((f) => f.id === fahrtId)

  const stationAnfahren = useCallback(async (s: Station) => {
    const runde = ++beweisRunde.current
    flow.setCenter(s.x, s.y, { zoom: s.zoom, duration: bewegungArm() ? 0 : s.dauer_ms })
    setFokus(s.fokus.length ? new Set(s.fokus) : null)
    if (!s.beweis_quelle) {
      setBeweisAnsicht(null)
      return
    }
    // Beweis-Station: erst hinfahren, dann das Dokument aufziehen.
    const aufDerWand = wand?.beweise.find((b) => b.quelle === s.beweis_quelle)?.quelle_detail
    const quelle = aufDerWand ?? (await akte.quelle(s.beweis_quelle).catch(() => null))
    if (!quelle || runde !== beweisRunde.current) return
    setTimeout(() => {
      if (runde === beweisRunde.current) setBeweisAnsicht({ quelle, zitat: s.beweis_zitat || undefined })
    }, bewegungArm() ? 0 : s.dauer_ms)
  }, [flow, wand])

  const schritt = useCallback((richtung: 1 | -1) => {
    if (!fahrt?.stationen.length) return
    const neu = Math.max(0, Math.min(fahrt.stationen.length - 1, stationIndex + richtung))
    setStationIndex(neu)
    stationAnfahren(fahrt.stationen[neu])
  }, [fahrt, stationIndex, stationAnfahren])

  const stationAufnehmen = useCallback(async (stichwort: string) => {
    if (!fahrt) return
    const p = mitte()
    const fokusIds = knoten.filter((n) => n.selected && n.type === "karte").map((n) => karteZuEntitaet.get(n.id)!.id)
    const neu: Station = { x: p.x, y: p.y, zoom: flow.getZoom(), fokus: fokusIds, stichwort, dauer_ms: 1400 }
    await akte.fahrtSpeichern(slug, { ...fahrt, stationen: [...fahrt.stationen, neu] })
    laden()
  }, [fahrt, mitte, knoten, karteZuEntitaet, flow, slug, laden])

  // ─── Gerenderte Aufnahme: Plan rechnen, dann Bild für Bild auf Zuruf ──────
  const knotenGemessen = useNodesInitialized()
  useEffect(() => {
    if (!render || !wand || !knotenGemessen) return
    const f = wand.fahrten.find((x) => x.id === render.fahrtId)
    const fmt = FORMATE[render.format]
    let plan: Plan | null = null
    const fehlendeBilder: string[] = []
    const vorladen = (url: string) => {
      const img = new Image()
      img.src = url
      vorgeladen.current.push(img)
      // Ein kaputtes Bild landet sonst lautlos im Video; der Renderer meldet die Liste als Warnung.
      return img.decode().catch(() => { fehlendeBilder.push(url) })
    }
    const bereit = (async () => {
      if (!f) throw new Error(`Die Fahrt ${render.fahrtId} gibt es auf diesem Board nicht.`)
      // Beweise vorab holen: während der Fahrt geht nichts mehr übers Netz.
      const quellen = new Map<number, Quelle>()
      for (const s of f.stationen) {
        if (!s.beweis_quelle || quellen.has(s.beweis_quelle)) continue
        const q = wand.beweise.find((b) => b.quelle === s.beweis_quelle)?.quelle_detail ?? await akte.quelle(s.beweis_quelle)
        quellen.set(s.beweis_quelle, q)
      }
      flushSync(() => setRenderQuellen(quellen))
      const urls = new Set<string>()
      for (const k of wand.karten) if (k.entitaet_detail.bild_url) urls.add(k.entitaet_detail.bild_url)
      for (const b of wand.beweise) if (b.quelle_detail.stand?.vorschau) urls.add(akte.dateiUrl(b.quelle_detail.stand.vorschau))
      for (const m of wand.mappen ?? []) for (const g of m.gesichter) if (g.bild_url) urls.add(g.bild_url)
      for (const s of f.stationen) {
        const q = s.beweis_quelle ? quellen.get(s.beweis_quelle) : undefined
        const bild = q ? bildFuerBeweis(q, s.beweis_zitat || undefined) : null
        if (bild) urls.add(akte.dateiUrl(bild))
      }
      await Promise.all([...urls].map(vorladen))
      await document.fonts.ready
      // Messen bei Zoom 1: unter 0,42 zeigen Karten nur den Namen und sind anders hoch.
      await flow.setViewport({ x: 0, y: 0, zoom: 1 }, { duration: 0 })
      for (let i = 0; i < 6; i++) await naechstesBild()
      await new Promise((fertig) => setTimeout(fertig, 150))
      await bilderFertig()
      // Rahmen aus den gemessenen Knoten, nicht aus geschätzten Kartenhöhen.
      const alle: Rechteck[] = []
      const kartenJe = new Map<number, FokusKarte>()
      for (const n of flow.getNodes()) {
        const b = n.measured?.width ?? n.width ?? 0
        const h = n.measured?.height ?? n.height ?? 0
        if (!b || !h) continue
        const r = { x: n.position.x, y: n.position.y, b, h }
        alle.push(r)
        if (n.type === "karte") {
          const e = (n.data as { entitaet: EntitaetKurz }).entitaet
          kartenJe.set(e.id, { ...r, titelPx: passendeGroesse(e.name, 26) })
        }
      }
      // Im Takt der Stimme: der Renderer legt die Satzanfänge vorher ins Fenster (scripts/akte/vertonen.py).
      const takt = window.__akteZeiten
      // Anzahl UND Satzanfänge müssen passen: sonst wurde die Fahrt nach dem Vertonen geändert.
      const getaktet = !!takt && takt.stationen.length === f.stationen.length &&
        (!takt.anfaenge || takt.anfaenge.every((a, i) => (f.stationen[i].text ?? "").trim().startsWith(a)))
      const gezeigteQuellen = new Set<string>()
      const eingaben: PlanEingabe[] = f.stationen.map((s, i) => {
        const karten = s.fokus.map((id) => kartenJe.get(id)).filter((k): k is FokusKarte => !!k)
        // Beschriftungen der Fäden, die in dieser Station leuchten, gehören ins Bild.
        const beiwerk = (render.etiketten === false ? [] : etikettLage.etiketten)
          .filter((e) => s.fokus.includes(e.von) && s.fokus.includes(e.nach))
          .map((e) => ({ x: e.x - e.b / 2, y: e.y - e.h / 2 + (etikettLage.versatz.get(e.id) ?? 0), b: e.b, h: e.h }))
        const einblendung = s.einblendung?.gross ? { ...s.einblendung, gross: s.einblendung.gross } : null
        // Unten steht die Zahlenkarte: die Kamera rahmt nur die Fläche darüber (auch beim Schwenk).
        const unten = !!einblendung && !einblendung.voll
        // Ein Zählwerk aus dem Schnitt liegt unten über dem Fenster: dort keine Karte
        const freiUnten = render.freiUnten ?? 0
        return {
          kameras: !karten.length
            ? [ueberblick(alle, fmt)]
            : unten ? rahmeUeberEinblendung(karten, fmt, beiwerk)
              : freiUnten > 0 ? rahmeUeberEinblendung(karten, fmt, beiwerk, freiUnten) : rahmeStation(karten, fmt, beiwerk),
          // Liegt keine Fokus-Karte mehr auf dem Board, zeigt die Station die ganze Wand — hell, nicht gedimmt.
          fokus: karten.length ? s.fokus : null,
          stichwort: render.stichworte ? s.stichwort : "",
          beweis: s.beweis_quelle ? { quelle: s.beweis_quelle, zitat: s.beweis_zitat || undefined } : null,
          fahrtMs: s.dauer_ms,
          einblendung,
          ankunftMs: getaktet ? takt.stationen[i] : undefined,
          einspieler: s.einspieler?.datei && typeof s.einspieler.bis === "number"
            ? {
              dauerMs: Math.round((s.einspieler.bis - (s.einspieler.ab ?? 0)) * 1000),
              freezeMs: s.einspieler.freeze_ms ?? 700,
              quelle: s.einspieler.quelle ?? "",
              untertitel: s.einspieler.untertitel,
              // Wie in vertonen.py: gleiche Quelle schon gezeigt → keine 5-s-Verlängerung.
              quelleGezeigt: gezeigteQuellen.has(s.einspieler.quelle ?? "") || !gezeigteQuellen.add(s.einspieler.quelle ?? ""),
            }
            : null,
        }
      })
      plan = zeitplan(eingaben, { ...STANDARD, halteMs: render.halteMs, bildBreite: fmt.b, endeMs: getaktet ? takt.ende_ms : undefined })
      return {
        dauerMs: plan.dauerMs,
        getaktet,
        fehlendeBilder,
        einspieler: f.stationen.flatMap((s, i) => (s.einspieler?.datei && typeof s.einspieler.bis === "number"
          ? [{ station: i, datei: s.einspieler.datei, ab: s.einspieler.ab ?? 0, bis: s.einspieler.bis }]
          : [])),
        stationen: plan.stationen.map((s) => ({ start: s.start, ankunft: s.ankunft, standbild: s.standbild, stichwort: s.eingabe.stichwort, kameras: s.eingabe.kameras,
          einspieler: s.einspieler ? { t0: s.einspieler.t0, laufBis: s.einspieler.laufBis } : null,
        })),
      }
    })()
    bereit.catch(() => undefined)
    window.__akteRender = {
      bereit: () => bereit,
      setzeZeit: async (ms: number) => {
        await bereit
        if (!plan) return
        const b = bildZu(plan, ms)
        flushSync(() => setRenderBild(b))
        await flow.setViewport(viewportVon(b.kamera, fmt), { duration: 0 })
        await naechstesBild()
        await naechstesBild()
        await bilderFertig()
      },
    }
    return () => { delete window.__akteRender }
  }, [render, wand, knotenGemessen, flow, etikettLage])

  // ─── Ankunft ──────────────────────────────────────────────────────────────
  const angekommen = useRef<string | null>(null)
  useEffect(() => {
    const ziel = `${ankunft?.karte ?? ""}|${ankunft?.aus ?? ""}`
    if (render || !wand || !knotenGemessen || angekommen.current === ziel) return
    angekommen.current = ziel
    const arm = bewegungArm()
    if (ankunft?.karte) {
      const k = wand.karten.find((x) => x.entitaet_detail.slug && x.entitaet_detail.slug === ankunft.karte)
      if (k) {
        flow.setCenter(k.x + 110, k.y + 190, { zoom: 1, duration: arm ? 0 : 700 })
        setAuswahl(k.entitaet)
        setFokus(new Set([k.entitaet]))
      }
      return
    }
    if (ankunft?.aus) {
      const m = wand.mappen?.find((x) => x.ziel === ankunft.aus)
      if (m) {
        // Wie aus der Mappe herausfahren: nah auf ihr beginnen, dann in den Überblick.
        const flaeche = document.querySelector(".react-flow")?.getBoundingClientRect()
        const k = eintauchKamera({ x: m.x, y: m.y, b: MAPPE_B, h: MAPPE_H }, { b: flaeche?.width ?? 1200, h: flaeche?.height ?? 800 })
        flow.setCenter(k.x, k.y, { zoom: k.zoom, duration: 0 })
        const t = setTimeout(() => flow.fitView({ duration: arm ? 0 : 800, padding: 0.1 }), 80)
        return () => clearTimeout(t)
      }
    }
  }, [render, wand, knotenGemessen, ankunft?.karte, ankunft?.aus, flow])

  // ─── Tastatur ─────────────────────────────────────────────────────────────
  useEffect(() => {
    function taste(e: KeyboardEvent) {
      const ziel = e.target as HTMLElement
      if (ziel.closest("input, textarea, select, [contenteditable]")) return
      // Offene Dialoge haben Vorrang — außer der Beweis-Ansicht: durch sie hindurch fährt die Aufnahme weiter.
      if (document.querySelector("[role='dialog']:not([data-beweis])")) return
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); if (!nurLesen) setBefehl(true); return }
      if (e.key === "Escape") {
        beweisRunde.current++
        if (beweisAnsicht) setBeweisAnsicht(null)
        else if (aufnahme) setAufnahme(false)
        else setFokus(null)
        return
      }
      if (e.key.toLowerCase() === "l") setLegende((l) => !l)
      if (e.altKey && e.key === "ArrowUp" && !aufnahme) { e.preventDefault(); hinauf(); return }
      if (e.key === "Enter" && !aufnahme) {
        const gewaehlt = knoten.find((n) => n.type === "mappe" && n.selected)
        if (gewaehlt) { e.preventDefault(); eintauchen((gewaehlt.data as { mappe: Mappe }).mappe); return }
      }
      if (!aufnahme) return
      if (e.key === "ArrowRight" || e.key === " " || e.key === "PageDown") { e.preventDefault(); schritt(1) }
      if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); schritt(-1) }
      if (e.key.toLowerCase() === "r") setRahmenhilfe((r) => (r === "16:9" ? "9:16" : r === "9:16" ? null : "16:9"))
      if (e.key.toLowerCase() === "f") setFokus(null)
      if (e.key.toLowerCase() === "s") setStichwortZeigen((z) => !z)
    }
    window.addEventListener("keydown", taste)
    return () => window.removeEventListener("keydown", taste)
  }, [aufnahme, nurLesen, schritt, beweisAnsicht, hinauf, knoten, eintauchen])

  const offeneFaeden = wand?.faeden.filter((f) => f.befunde.length).length ?? 0

  if (fehler) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-6 text-center">
        <p role="alert">{fehler}</p>
        <Link href="/akte" className="text-[#f0c674] underline">Zurück zur Übersicht</Link>
        {/* Seit 03.10.2026 ist /akte/<slug> ohne Login offen: Wer als Mitglied abgelaufen ist, braucht den Weg zurück. */}
        <Link href={`/login?redirect=${encodeURIComponent(`/akte/${slug}`)}`} className="text-[#8A94A0] underline">Anmelden</Link>
      </div>
    )
  }

  return (
    <div
      className={`relative h-full w-full${render ? " akte-render" : ""}`}
      style={{ background: papier ? "#c9a878" : FARBEN.grund }}
      onDragOver={(e) => { if (!gesperrt && e.dataTransfer.types.includes("Files")) { e.preventDefault(); setZiehtDatei(true) } }}
      onDragLeave={(e) => { if (e.currentTarget === e.target) setZiehtDatei(false) }}
      onDrop={(e) => { if (!gesperrt) dateienAblegen(e) }}
    >
      <style>{WAND_CSS}</style>
      <ReactFlow
        nodes={knoten}
        edges={kanten}
        nodeTypes={knotenTypen}
        edgeTypes={alleKantenTypen}
        onNodesChange={onNodesChange}
        onNodeDragStop={onNodeDragStop}
        onConnect={onConnect}
        onNodesDelete={onNodesDelete}
        onEdgesDelete={onEdgesDelete}
        onNodeClick={(_, n) => { if (n.type === "karte" && !aufnahme) setAuswahl(karteZuEntitaet.get(n.id)!.id) }}
        onNodeDoubleClick={(_, n) => {
          if (n.type === "beweis") setBeweisAnsicht({ quelle: (n.data as { quelle: Quelle }).quelle })
          if (n.type === "mappe" && !aufnahme) eintauchen((n.data as { mappe: Mappe }).mappe)
        }}
        onEdgeClick={(_, e) => {
          if (aufnahme) return
          if (e.type === "buendel") {
            setAuswahl(null)
            setBuendelOffen((e.data as { buendel: Buendel }).buendel.id)
            return
          }
          const v = (e.data as { verbindung: Verbindung }).verbindung
          if (nurLesen) setFadenLesen(v)
          else fadenOeffnen(v)
        }}
        onPaneClick={() => { setAuswahl(null); setBuendelOffen(null) }}
        connectionMode={ConnectionMode.Loose}
        snapToGrid
        snapGrid={[20, 20]}
        connectionLineStyle={{ stroke: FARBEN.rot, strokeWidth: 3 }}
        deleteKeyCode={gesperrt ? null : ["Delete", "Backspace"]}
        nodesDraggable={!gesperrt}
        nodesConnectable={!gesperrt}
        elementsSelectable={!aufnahme}
        minZoom={0.1}
        maxZoom={3}
        fitView
        fitViewOptions={{ padding: 0.1 }}
        proOptions={{ hideAttribution: true }}
      >
        <Background
          variant={papier ? BackgroundVariant.Dots : BackgroundVariant.Lines}
          gap={papier ? 18 : 64}
          size={papier ? 1.4 : 1}
          color={papier ? "#a88a5e" : "#15171f"}
        />
        {!aufnahme && <Controls position="bottom-left" showInteractive={false} />}
        {!aufnahme && (
          <MiniMap pannable zoomable position="bottom-right"
            style={{ background: "#0d0e14", marginRight: auswahl ? 436 : 16 }}
            nodeColor={(n) => n.type === "karte"
              ? TYP_FARBE[(n.data as { entitaet: EntitaetKurz }).entitaet.typ] ?? FARBEN.rot
              : n.type === "zettel" ? "#FFD54F" : n.type === "beweis" ? "#EDE6D8" : n.type === "mappe" ? "#d9b77a" : "transparent"}
            maskColor="rgba(10,10,15,0.6)" />
        )}
      </ReactFlow>

      {!aufnahme && wand && nurLesen && (
        <LeseKopf brotkrumen={<Brotkrumen pfad={pfad} titelJe={titelJe} aktuell={wand.board.titel} slug={slug} />} />
      )}

      {!aufnahme && wand && !nurLesen && (
        <Werkzeugleiste
          brotkrumen={<Brotkrumen pfad={pfad} titelJe={titelJe} aktuell={wand.board.titel} slug={slug} />}
          mappenWahl={(boardsListe ?? []).filter((b) => b.slug !== slug && !(wand.mappen ?? []).some((m) => m.ziel === b.slug))}
          mappe={mappeNeu}
          gelenke={wand.gelenke ?? []}
          gelenkeHolen={gelenkeHolen}
          offeneFaeden={offeneFaeden}
          karte={() => setBefehl(true)}
          zettel={zettelNeu}
          rahmen={rahmenNeu}
          weg={wegFinden}
          fahrten={() => setFahrtenOffen((o) => !o)}
          aufnahme={() => { setAuswahl(null); setAufnahmeDialog(true) }}
          amRechner={amRechner}
          aufraeumen={aufraeumen}
          datei={() => dateiWahl.current?.click()}
          fokusAktiv={!!fokus}
          fokusWeg={() => setFokus(null)}
        />
      )}

      {legende && wand && <Legende aufnahme={aufnahme} papier={papier} />}

      <input
        ref={dateiWahl}
        type="file"
        multiple
        accept="application/pdf,image/png,image/jpeg,image/webp,image/gif"
        className="sr-only"
        tabIndex={-1}
        aria-hidden
        onChange={(e) => {
          const dateien = [...(e.target.files ?? [])]
          e.target.value = ""
          dateienSichern(dateien, mitte())
        }}
      />

      {ziehtDatei && (
        <div className="pointer-events-none absolute inset-4 z-40 flex items-center justify-center rounded-xl border-2 border-dashed border-[#f0c674] bg-[#f0c674]/10">
          <p className="font-[family-name:var(--font-akte-titel)] text-4xl uppercase tracking-wide text-[#f0c674]">
            Loslassen: wird gesichert und als Beweisstück angepinnt
          </p>
        </div>
      )}

      {aufnahme && !render && <AufnahmeHilfe rahmenhilfe={rahmenhilfe} fahrt={fahrt} index={stationIndex} />}

      {aufnahme && !render && stichwortZeigen && fahrt && stationIndex >= 0 && fahrt.stationen[stationIndex]?.stichwort && (
        <Bauchbinde text={fahrt.stationen[stationIndex].stichwort} deckkraft={1} links={48} unten={48} papier={papier} />
      )}

      {render && renderBild && renderBild.stichwort.deckkraft > 0 && (
        <Bauchbinde
          text={renderBild.stichwort.text}
          deckkraft={renderBild.stichwort.deckkraft}
          links={FORMATE[render.format].rand.l}
          unten={FORMATE[render.format].rand.u}
          papier={papier}
        />
      )}

      {render && renderBild?.einspieler && (
        <EinspielerAnsicht e={renderBild.einspieler} format={FORMATE[render.format]} hoch={render.format === "9x16"} />
      )}

      {render && renderBild?.einblendung && (
        <EinblendungKarte e={renderBild.einblendung} format={FORMATE[render.format]} papier={papier} />
      )}

      {render && renderBild?.beweis && renderQuellen.get(renderBild.beweis.quelle) && (
        <BeweisAnsicht
          key={`${renderBild.station}-${renderBild.beweis.quelle}`}
          quelle={renderQuellen.get(renderBild.beweis.quelle)!}
          zitat={renderBild.beweis.zitat}
          schliessen={() => undefined}
          render={{ rein: renderBild.beweis.rein, raus: renderBild.beweis.raus }}
        />
      )}

      {!aufnahme && fahrtenOffen && wand && (
        <FahrtenLeiste
          slug={slug}
          fahrten={wand.fahrten}
          aktiv={fahrtId}
          waehlen={(id) => { setFahrtId(id); setStationIndex(-1) }}
          stationAufnehmen={stationAufnehmen}
          anfahren={(i) => { setStationIndex(i); if (fahrt) stationAnfahren(fahrt.stationen[i]) }}
          geaendert={laden}
          schliessen={() => setFahrtenOffen(false)}
        />
      )}

      {!aufnahme && nurLesen && auswahl !== null && wand && (() => {
        const karte = namenJe.get(auswahl)
        return karte ? (
          <KarteLesen key={auswahl} karte={karte} faeden={wand.faeden} namen={namenJe}
            auchIn={wand.auch_in?.[String(auswahl)] ?? []}
            springen={(ziel) => router.push(`/akte/${ziel}?${new URLSearchParams({ karte: karte.slug }).toString()}`)}
            schliessen={() => setAuswahl(null)} karteOeffnen={(e) => karteHolen(e)} />
        ) : null
      })()}

      {!aufnahme && !nurLesen && auswahl !== null && (
        <NotizLeiste
          key={auswahl}
          id={auswahl}
          schliessen={() => setAuswahl(null)}
          geaendert={laden}
          fadenOeffnen={fadenOeffnen}
          linkFolgen={linkFolgen}
          karteOeffnen={(e) => karteHolen(e)}
          anDieWand={(q) => quelleAnDieWand(q.id)}
          zeigen={(q, zitat) => setBeweisAnsicht({ quelle: q, zitat })}
        />
      )}

      {!aufnahme && buendelOffen && wand && (() => {
        const bu = wand.buendel?.find((b) => b.id === buendelOffen)
        if (!bu) return null
        const titel = (knotenId: string) => {
          const [art, id] = knotenId.split("-")
          if (art === "m") return wand.mappen?.find((m) => m.id === Number(id))?.titel ?? "Mappe"
          return wand.karten.find((k) => k.id === Number(id))?.entitaet_detail.name ?? "?"
        }
        return (
          <BuendelLeiste
            key={bu.id}
            buendel={bu}
            faeden={wand.buendel_faeden ?? []}
            namen={alleNamen}
            titelVon={titel(bu.von)}
            titelNach={titel(bu.nach)}
            schliessen={() => setBuendelOffen(null)}
            bearbeiten={nurLesen ? undefined : (v) => fadenOeffnen(v)}
            ausblenden={nurLesen ? undefined : async (v) => {
              try {
                const r = await akte.fadenAusblenden(slug, v.id)
                melden(r.ausgeblendet
                  ? "Faden auf dieser Wand ausgeblendet. Er bleibt in der Akte und in seiner Mappe."
                  : "Faden wieder eingeblendet.")
              } catch {
                melden("Umschalten fehlgeschlagen.")
              }
              laden()
            }}
          />
        )
      })()}

      {tauchen && !render && (
        <div aria-hidden className="pointer-events-none absolute inset-0 z-50 bg-[#d9b77a] akte-tauchen" />
      )}

      {aufnahmeDialog && wand && (
        <AufnahmeDialog
          board={slug}
          fahrten={wand.fahrten}
          fahrtId={fahrtId}
          schliessen={() => setAufnahmeDialog(false)}
          live={(id) => {
            setAufnahmeDialog(false)
            setFahrtId(id)
            setStationIndex(-1)
            setAufnahme(true)
            setLegende(false)
          }}
        />
      )}

      {befehl && <Befehlszeile schliessen={() => setBefehl(false)} gewaehlt={(e) => karteHolen(e)} />}

      {fadenDialog && (
        <FadenFormular
          {...fadenDialog}
          fertig={(v) => { setFadenDialog(null); if (v) laden() }}
        />
      )}

      {fadenLesen && (
        <FadenLesen v={fadenLesen} von={alleNamen.get(fadenLesen.von)} nach={alleNamen.get(fadenLesen.nach)}
          schliessen={() => setFadenLesen(null)} />
      )}

      {beweisAnsicht && (
        <BeweisAnsicht quelle={beweisAnsicht.quelle} zitat={beweisAnsicht.zitat} schliessen={() => setBeweisAnsicht(null)} />
      )}

      {meldung && !render && (
        <p role="status" className="absolute bottom-6 left-1/2 z-40 -translate-x-1/2 rounded-md border border-[#222636] bg-[#101117] px-4 py-2 text-sm shadow-xl">
          {meldung}
        </p>
      )}
    </div>
  )
}

// ─── Werkzeugleiste ─────────────────────────────────────────────────────────

function Werkzeugleiste(p: {
  brotkrumen: React.ReactNode
  mappenWahl: Board[]
  mappe: (ziel: string) => void
  gelenke: EntitaetKurz[]
  gelenkeHolen: () => void
  offeneFaeden: number
  karte: () => void
  zettel: (art: Zettel["art"]) => void
  rahmen: (titel: string) => void
  weg: () => void
  fahrten: () => void
  aufnahme: () => void
  amRechner: boolean
  aufraeumen: () => void
  datei: () => void
  fokusAktiv: boolean
  fokusWeg: () => void
}) {
  const [rahmenTitel, setRahmenTitel] = useState<string | null>(null)
  const [mappeOffen, setMappeOffen] = useState(false)
  const mappeMenue = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!mappeOffen) return
    const klick = (e: MouseEvent) => { if (!mappeMenue.current?.contains(e.target as globalThis.Node)) setMappeOffen(false) }
    const taste = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); setMappeOffen(false) } }
    document.addEventListener("mousedown", klick)
    window.addEventListener("keydown", taste, true)
    return () => { document.removeEventListener("mousedown", klick); window.removeEventListener("keydown", taste, true) }
  }, [mappeOffen])
  const knopf = "flex min-h-10 cursor-pointer items-center gap-2 rounded-md px-3 text-sm text-[#F2F7FB] transition-colors duration-200 hover:bg-white/10"
  return (
    <div className="absolute left-4 top-4 z-20 flex max-w-[calc(100%-2rem)] flex-wrap items-center gap-1 rounded-lg border border-[#222636] bg-[#0d0e14]/90 p-1.5 backdrop-blur">
      <Link href="/akte" aria-label="Zur Übersicht" className={knopf}><ArrowLeft className="h-4 w-4" /></Link>
      {p.brotkrumen}
      <button type="button" className={knopf} onClick={p.karte} title="Strg+K"><Search className="h-4 w-4" aria-hidden /> Karte</button>
      <button type="button" className={knopf} onClick={() => p.zettel("notiz")}><StickyNote className="h-4 w-4" aria-hidden /> Notiz</button>
      <button type="button" className={knopf} onClick={() => p.zettel("meinung")}><StickyNote className="h-4 w-4 text-[#FFD54F]" aria-hidden /> Meinung</button>
      <button type="button" className={knopf} onClick={() => p.zettel("frage")}><StickyNote className="h-4 w-4 text-[#B3E5FC]" aria-hidden /> Frage</button>
      {rahmenTitel === null ? (
        <button type="button" className={knopf} onClick={() => setRahmenTitel("")}><Frame className="h-4 w-4" aria-hidden /> Rahmen</button>
      ) : (
        <form onSubmit={(e) => { e.preventDefault(); if (rahmenTitel.trim()) p.rahmen(rahmenTitel.trim()); setRahmenTitel(null) }}>
          <input autoFocus aria-label="Titel des Rahmens" placeholder="Titel, Enter" value={rahmenTitel}
            onChange={(e) => setRahmenTitel(e.target.value)} onBlur={() => setRahmenTitel(null)}
            className="h-10 w-40 rounded-md border border-[#f0c674] bg-transparent px-2 text-sm outline-none" />
        </form>
      )}
      <div className="relative" ref={mappeMenue}>
        <button type="button" className={knopf} onClick={() => setMappeOffen((o) => !o)} aria-expanded={mappeOffen}
          title="Ein anderes Board als Aktenmappe auf diese Wand legen">
          <FolderPlus className="h-4 w-4" aria-hidden /> Mappe
        </button>
        {mappeOffen && (
          <ul aria-label="Board als Mappe wählen" className="absolute left-0 top-full z-30 mt-1 max-h-80 w-72 overflow-y-auto rounded-md border border-[#222636] bg-[#0d0e14] p-1 shadow-xl">
            {p.mappenWahl.length === 0 && <li className="px-3 py-2 text-sm text-[#8A94A0]">Alle Boards liegen schon hier.</li>}
            {p.mappenWahl.map((b) => (
              <li key={b.slug}>
                <button type="button" onClick={() => { setMappeOffen(false); p.mappe(b.slug) }}
                  className="flex min-h-10 w-full cursor-pointer flex-col items-start rounded px-3 py-1.5 text-left hover:bg-white/10">
                  <span className="text-sm">{b.titel}</span>
                  <span className="font-[family-name:var(--font-akte-mono)] text-[10px] text-[#8A94A0]">{b.slug}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {p.gelenke.length > 0 && (
        <button type="button" className={`${knopf} text-[#f0c674]`} onClick={p.gelenkeHolen}
          title={`In mehreren Mappen, aber nicht auf dieser Wand: ${p.gelenke.map((g) => g.name).join(", ")}`}>
          <GitMerge className="h-4 w-4" aria-hidden /> {p.gelenke.length} Gelenk{p.gelenke.length === 1 ? "" : "e"} holen
        </button>
      )}
      <button type="button" className={knopf} onClick={p.datei} title="PDF oder Bild sichern und als Beweisstück anpinnen (oder einfach auf die Wand ziehen)">
        <Paperclip className="h-4 w-4" aria-hidden /> Beweis
      </button>
      <button type="button" className={knopf} onClick={p.aufraeumen} title="Alles ordentlich ins Raster, nichts überlappt">
        <LayoutGrid className="h-4 w-4" aria-hidden /> Aufräumen
      </button>
      <button type="button" className={knopf} onClick={p.weg} title="Zwei Karten wählen"><Route className="h-4 w-4" aria-hidden /> Weg</button>
      {p.fokusAktiv && (
        <button type="button" className={`${knopf} text-[#f0c674]`} onClick={p.fokusWeg}>Scheinwerfer aus</button>
      )}
      {p.amRechner && (
        <>
          <button type="button" className={knopf} onClick={p.fahrten}><MapPin className="h-4 w-4" aria-hidden /> Fahrten</button>
          <button type="button" className={`${knopf} bg-[#FF1744]/15 text-[#FF1744] hover:bg-[#FF1744]/25`} onClick={p.aufnahme}>
            <Video className="h-4 w-4" aria-hidden /> Aufnahme
          </button>
        </>
      )}
      {p.offeneFaeden > 0 && (
        <span className="ml-1 rounded-full bg-[#FFB300]/15 px-3 py-1 text-xs text-[#FFB300]" title="Diese Fäden bestehen die Veröffentlichungs-Prüfung noch nicht">
          {p.offeneFaeden} {p.offeneFaeden === 1 ? "Faden" : "Fäden"} nicht veröffentlichbar
        </span>
      )}
    </div>
  )
}

// ─── Kopf für Mitglieder: Titel und Hinweis statt Werkzeugen ──────────────

function LeseKopf({ brotkrumen }: { brotkrumen: React.ReactNode }) {
  return (
    <div className="absolute left-4 top-4 z-20 flex max-w-[calc(100%-2rem)] flex-wrap items-center gap-3 rounded-lg border border-[#222636] bg-[#0d0e14]/90 p-1.5 pr-4 backdrop-blur">
      <Link href="/akte" aria-label="Zur Übersicht" className="flex min-h-10 items-center rounded-md px-3 hover:bg-white/10"><ArrowLeft className="h-4 w-4" /></Link>
      {brotkrumen}
      <span className="text-xs text-[#8A94A0]">Nur lesen. Jede Verbindung trägt ihre Quelle, Meinungen stehen auf eigenen Zetteln. Die Recherche geht weiter.</span>
    </div>
  )
}

// ─── Legende: was die Fäden bedeuten ───────────────────────────────────────

function Legende({ aufnahme, papier }: { aufnahme: boolean; papier: boolean }) {
  const eintrag = "flex items-center gap-2"
  return (
    <div
      className={`pointer-events-none absolute z-20 flex flex-wrap items-center gap-x-5 gap-y-1 rounded-md px-4 py-2 font-[family-name:var(--font-akte-mono)] text-[12px] uppercase tracking-widest ${aufnahme ? "bottom-6 left-6" : "bottom-4 left-20"}`}
      style={{ background: papier ? "rgba(251,248,241,0.92)" : "rgba(13,14,20,0.88)", color: papier ? "#141318" : "#F2F7FB" }}
      aria-label="Legende"
    >
      <span className={eintrag}><svg width="34" height="6" aria-hidden><line x1="0" y1="3" x2="34" y2="3" stroke={FARBEN.rot} strokeWidth="3" /></svg>Belegt</span>
      <span className={eintrag}><svg width="34" height="6" aria-hidden><line x1="0" y1="3" x2="34" y2="3" stroke={FARBEN.rot} strokeWidth="2.5" strokeDasharray="7 5" /></svg>Verdacht</span>
      <span className={eintrag}><svg width="34" height="6" aria-hidden><line x1="0" y1="3" x2="34" y2="3" stroke={FARBEN.ocker} strokeWidth="2.5" strokeDasharray="2 5" strokeLinecap="round" /></svg>Meinung</span>
      <span className={eintrag}><svg width="34" height="6" aria-hidden><line x1="0" y1="3" x2="34" y2="3" stroke={FARBEN.gold} strokeWidth="1.5" strokeDasharray="3 6" /></svg>Beweisstück</span>
    </div>
  )
}

// ─── Render-Modus: Fäden aus der Zeit ───────────────────────────────────────

function fadenRender(b: Bild, von: number, nach: number) {
  const l = fadenLicht(b.fokus, von, nach)
  return { hell: l.hell, hervor: l.hervor, zug: l.neu ? b.fadenZug : 1 }
}

// ─── Einspieler: O-Ton-Clip gerahmt über der Wand, mit Quellenmarke ─────────

function EinspielerAnsicht({ e, format, hoch }: {
  e: NonNullable<Bild["einspieler"]>
  format: (typeof FORMATE)[FormatKennung]
  hoch: boolean
}) {
  const sicht = e.rein * (1 - e.raus)
  const s = Math.min(format.b, format.h) / 1080
  // Querformat: gut drei Viertel der Breite; Hochformat: volle sichere Breite, etwas über der Mitte.
  const breite = hoch ? format.b - format.rand.l - format.rand.r : format.b * 0.74
  return (
    <div
      className="pointer-events-none absolute inset-0 z-40 flex flex-col items-center justify-center"
      style={{ background: `rgba(5,5,8,${(hoch ? 0.93 : 0.85) * sicht})`, paddingBottom: hoch ? format.h * 0.08 : 0 }}
    >
      <div
        className="relative bg-black shadow-[0_30px_80px_rgba(0,0,0,0.75)]"
        style={{
          width: breite, aspectRatio: "16 / 9", opacity: sicht,
          transform: `scale(${0.94 + 0.06 * e.rein})`, outline: `${3 * s}px solid #F2F7FB22`,
        }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- Einzelbild des Clips, vom Renderer ausgeliefert */}
        <img
          src={`/__einspieler/${e.station}/${String(e.bild).padStart(5, "0")}.jpg`}
          alt=""
          className="h-full w-full object-contain"
        />
        <span
          className="absolute font-[family-name:var(--font-akte-mono)] font-semibold uppercase tracking-[0.25em] text-white"
          style={{ left: 14 * s, top: 14 * s, fontSize: 18 * s, padding: `${4 * s}px ${10 * s}px`, background: "#FF1744" }}
        >
          O-Ton
        </span>
      </div>
      {e.untertitel && (
        // Deutsche Übersetzung des O-Tons: groß und gut lesbar, direkt unter dem Clip.
        <p
          className="mt-5 text-center font-semibold leading-snug text-[#F2F7FB]"
          style={{ fontSize: (hoch ? 44 : 34) * s, maxWidth: breite, opacity: sicht }}
        >
          {e.untertitel}
        </p>
      )}
      <p
        className="mt-4 max-w-[90%] text-center font-[family-name:var(--font-akte-mono)] tracking-[0.08em] text-[#C9CED6]"
        style={{ fontSize: 17 * s, opacity: sicht }}
      >
        Quelle: {e.quelle}
      </p>
    </div>
  )
}

// ─── Einblendung: Zahl oder Zitat groß über der Wand ────────────────────────

function EinblendungKarte({ e, format, papier }: {
  e: NonNullable<Bild["einblendung"]>
  format: (typeof FORMATE)[FormatKennung]
  papier: boolean
}) {
  const sicht = e.rein * (1 - e.raus)
  const zitat = /^[„"»]/.test(e.gross)
  // Schrift nach der kurzen Kante: im Hochformat gleich groß lesbar wie im Querformat.
  const s = Math.min(format.b, format.h) / 1080
  if (e.voll) {
    return (
      <div
        className="pointer-events-none absolute inset-0 z-30 flex flex-col items-center justify-center text-center"
        style={{ background: `rgba(5,5,8,${0.86 * sicht})`, padding: `0 ${format.rand.l}px` }}
      >
        <p
          className="font-[family-name:var(--font-akte-titel)] uppercase leading-[0.95] text-[#F2F7FB]"
          style={{ fontSize: 150 * s, opacity: sicht, transform: `scale(${0.94 + 0.06 * e.rein})` }}
        >
          {e.gross}
        </p>
        {e.klein && <p className="mt-4 text-[#8A94A0]" style={{ fontSize: 34 * s, opacity: sicht }}>{e.klein}</p>}
      </div>
    )
  }
  return (
    <>
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 bottom-0 z-20"
        style={{ height: "46%", background: "linear-gradient(to top, rgba(5,5,8,0.9), rgba(5,5,8,0))", opacity: sicht }}
      />
      <div
        className="pointer-events-none absolute z-30 flex items-stretch"
        style={{
          left: format.rand.l, bottom: format.rand.u, gap: 22 * s, opacity: sicht,
          transform: `translateY(${(1 - e.rein) * 40 * s}px)`,
        }}
      >
        <span aria-hidden className="bg-[#FF1744]" style={{ width: 8 * s }} />
        <div>
          <p
            // Zitate in ihrer Schreibung (Anführungszeichen, Kleinbuchstaben), Zahlen und Schlagworte in Versalien.
            className={`font-[family-name:var(--font-akte-titel)] ${zitat ? "leading-[1.12]" : "uppercase leading-[0.95]"}`}
            style={{
              // Kurze Zahl riesig, ein Zitat kleiner und umbrochen (höchstens gut die halbe Bildbreite).
              fontSize: (e.gross.length > 14 ? 76 : 130) * s,
              maxWidth: format.b * 0.62,
              // Das öffnende Anführungszeichen hängt in den Rand, die Buchstaben stehen bündig.
              textIndent: zitat ? "-0.35em" : undefined,
              color: papier ? "#141318" : "#F2F7FB",
            }}
          >
            {e.gross}
          </p>
          {e.klein && (
            <p className="mt-2 font-medium" style={{ fontSize: 36 * s, color: papier ? "#2a2830" : "#F2F7FB" }}>{e.klein}</p>
          )}
          {e.quelle && (
            <p
              className="mt-3 font-[family-name:var(--font-akte-mono)] uppercase tracking-[0.2em]"
              style={{ fontSize: 17 * s, color: papier ? "#5a5560" : "#8A94A0" }}
            >
              Quelle: {e.quelle}
            </p>
          )}
        </div>
      </div>
    </>
  )
}

// ─── Bauchbinde: das Stichwort der Station, dezent unten links ─────────────

function Bauchbinde(p: { text: string; deckkraft: number; links: number; unten: number; papier: boolean }) {
  return (
    <div
      className="pointer-events-none absolute z-30 flex items-stretch gap-3"
      style={{ left: p.links, bottom: p.unten, opacity: p.deckkraft, transform: `translateX(${(1 - p.deckkraft) * -24}px)` }}
    >
      <span aria-hidden className="w-[6px] bg-[#FF1744]" />
      <span
        className="px-4 py-2 font-[family-name:var(--font-akte-titel)] text-[44px] uppercase leading-none tracking-wide"
        style={{ background: p.papier ? "rgba(251,248,241,0.94)" : "rgba(10,10,15,0.86)", color: p.papier ? "#141318" : "#F2F7FB" }}
      >
        {p.text}
      </span>
    </div>
  )
}

// ─── Aufnahme-Modus: nur Rahmenhilfe, sonst nichts ─────────────────────────

function AufnahmeHilfe({ rahmenhilfe, fahrt, index }: { rahmenhilfe: Rahmenhilfe; fahrt?: Fahrt; index: number }) {
  const [hinweis, setHinweis] = useState(true)
  useEffect(() => { const t = setTimeout(() => setHinweis(false), 4000); return () => clearTimeout(t) }, [])
  return (
    <>
      {rahmenhilfe && (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center">
          <div
            className="border border-dashed border-white/25"
            style={{
              aspectRatio: rahmenhilfe === "16:9" ? "16 / 9" : "9 / 16",
              height: rahmenhilfe === "16:9" ? "auto" : "100%",
              width: rahmenhilfe === "16:9" ? "100%" : "auto",
              maxHeight: "100%",
              maxWidth: "100%",
              boxShadow: "0 0 0 9999px rgba(0,0,0,0.35)",
            }}
          />
        </div>
      )}
      {hinweis && (
        <p className="pointer-events-none absolute bottom-6 left-1/2 z-20 -translate-x-1/2 rounded-md bg-black/80 px-4 py-2 font-[family-name:var(--font-akte-mono)] text-xs text-[#8A94A0]">
          {fahrt ? `Fahrt „${fahrt.titel}“ · ${fahrt.stationen.length} Stationen · → weiter · ← zurück` : "Keine Fahrt gewählt"} · R Rahmen · L Legende · S Stichwort · F Scheinwerfer aus · Esc Ende
          {index >= 0 && ` · Station ${index + 1}`}
        </p>
      )}
    </>
  )
}

const WAND_CSS = `
.react-flow__handle.akte-nadel { width: 18px; height: 18px; background: transparent; border: none; top: 0; }
.react-flow__node:hover .react-flow__handle.akte-nadel { background: rgba(255,23,68,0.35); border-radius: 9999px; }
.react-flow__edgelabel-renderer { z-index: 6; }
.react-flow__controls button { background: #101117; border-color: #222636; fill: #F2F7FB; }
.akte-faden-zieh { stroke-dasharray: 1; stroke-dashoffset: 1; animation: akte-zieh 700ms ease-out forwards; }
.akte-faden-blende { animation: akte-blende 500ms ease-out; }
@keyframes akte-zieh { to { stroke-dashoffset: 0; } }
@keyframes akte-blende { from { opacity: 0; } }
.akte-beweis-rein { animation: akte-beweis 520ms cubic-bezier(.2,.8,.2,1); }
.akte-beweis-rein .akte-blatt { animation: akte-blatt 620ms cubic-bezier(.2,.8,.2,1); }
@keyframes akte-beweis { from { background-color: rgba(0,0,0,0); backdrop-filter: blur(0); } }
@keyframes akte-blatt { from { opacity: 0; transform: translateY(60px) rotate(-5deg) scale(.96); } }
.akte-tauchen { animation: akte-tauchen 430ms ease-in forwards; }
@keyframes akte-tauchen { from { opacity: 0; } 60% { opacity: 0.2; } to { opacity: 1; } }
.akte-render, .akte-render * { transition: none !important; animation: none !important; cursor: none !important; caret-color: transparent; }
@media (prefers-reduced-motion: reduce) { .akte-faden-zieh, .akte-faden-blende, .akte-beweis-rein, .akte-beweis-rein .akte-blatt { animation: none; stroke-dashoffset: 0; } }
`
