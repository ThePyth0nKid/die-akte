"use client"

// Die Knoten der Wand: Karte (mit Stecknadel), Zettel und Rahmen.

import { memo, useState } from "react"
import { Handle, NodeResizer, Position, useStore, type Node, type NodeProps } from "@xyflow/react"
import { AlertTriangle, Archive, CornerDownRight, FileText, Hash } from "lucide-react"
import { akte } from "@/lib/akte/api"
import { FARBEN, rahmenStil } from "@/lib/akte/faden"
import { bildArt, passendeGroesse } from "@/lib/akte/ordnung"
import { TYP_NAMEN, type BoardVerweis, type EntitaetKurz, type Quelle, type Zettel } from "@/lib/akte/typen"
import { MappeKnoten } from "./MappeKnoten"
import { datum, kopieVon } from "./QuellenVorschau"
import Siegel from "./Siegel"

/** Alle Fäden hängen an derselben Nadel oben auf der Karte. */
function Nadel({ farbe = FARBEN.rot }: { farbe?: string }) {
  return (
    <>
      <span
        aria-hidden
        className="absolute left-1/2 top-0 z-10 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full shadow-[0_2px_4px_rgba(0,0,0,0.6)]"
        style={{ background: `radial-gradient(circle at 35% 35%, #fff8 0%, ${farbe} 45%, #600 100%)` }}
      />
      <Handle id="nadel" type="source" position={Position.Top} className="akte-nadel" />
    </>
  )
}

export type KarteDaten = {
  entitaet: EntitaetKurz
  befunde: number
  gedimmt: boolean
  /** Im Render-Modus: Deckkraft aus der Zeit, statt CSS-Übergang. */
  deckkraft?: number
  aufnahme: boolean
  papier: boolean
  /** Mitglied: kein Entwurfs-Stempel an jeder Karte (steht einmal oben). */
  nurLesen?: boolean
  /** Portale: andere Wände, auf denen dieselbe Karte liegt („auch in …“). */
  auchIn?: BoardVerweis[]
  springen?: (slug: string) => void
  /** Gerade live auf die Wand gekommen: kurz hervorheben. */
  neu?: boolean
}
export type KarteKnotenTyp = Node<KarteDaten, "karte">

function initialen(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((t) => t[0]).join("").toUpperCase()
}

/** Unter diesem Zoom zeigt die Karte nur noch den Namen, groß — der Überblick bleibt lesbar. */
const NUR_NAME_UNTER = 0.42

export const KarteKnoten = memo(function KarteKnoten({ data, selected }: NodeProps<KarteKnotenTyp>) {
  const e = data.entitaet
  const person = e.typ === "person"
  const fern = useStore((z) => z.transform[2] < NUR_NAME_UNTER)
  const art = bildArt(e.bild_nachweis)
  // Platzhalter-Bilder („KP · PERSON · KEIN FOTO“) und ihr Nachweis „Platzhalter (kein freies Foto gefunden)“ sind Bauhinweise:
  // in Aufnahme und Render nie zeigen, dort stehen die Initialen. Die Daten bleiben,
  // der Präfix ist das Erkennungsmerkmal für Export und Inventar.
  const platzhalter = !!data.aufnahme && /^Platzhalter/i.test(e.bild_nachweis ?? "")
  const bildUrl = platzhalter ? "" : e.bild_url
  return (
    <div
      className={`relative w-[220px] transition-opacity duration-300${data.neu ? " akte-neu" : ""}`}
      style={{ opacity: data.deckkraft ?? (data.gedimmt ? 0.12 : 1) }}
    >
      <Nadel />
      <div
        className="akte-karte-blatt rounded-[3px] p-3 pb-4 shadow-[0_10px_24px_rgba(0,0,0,0.55)]"
        style={{
          background: data.papier ? "#fbf8f1" : "#15161d",
          color: data.papier ? FARBEN.tinteDunkel : FARBEN.tinte,
          outline: selected && !data.aufnahme ? `2px solid ${FARBEN.gold}` : "none",
          outlineOffset: 3,
          transform: `rotate(${((e.id * 37) % 5) - 2}deg)`,
        }}
      >
        {fern ? (
          <p
            lang="de"
            className="flex min-h-[180px] items-center break-words font-[family-name:var(--font-akte-titel)] uppercase leading-[0.95]"
            style={{ fontSize: passendeGroesse(e.name, 44) }}
          >
            {e.name}
          </p>
        ) : person || bildUrl ? (
          <div
            className="relative mb-3 flex aspect-square w-full items-center justify-center overflow-hidden"
            style={{
              filter: person ? "grayscale(0.35) contrast(1.05)" : undefined,
              // Zeichen (Logo, Siegel, Wappen) sind oft dunkel auf durchsichtig: heller Grund, sonst verschwinden sie.
              background: bildUrl && art === "zeichen" ? "#EDE6D8" : "#222636",
            }}
          >
            {bildUrl ? (
              <>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={bildUrl}
                  alt={e.name}
                  // Zeichen ganz und mit Rand, CC BY-SA / BY-ND unbeschnitten (Hausregel), sonst füllend.
                  className={`h-full w-full ${art === "zeichen" ? "object-contain px-4 pb-7 pt-4" : art === "unbeschnitten" ? "object-contain" : "object-cover"}`}
                  draggable={false}
                />
                {e.bild_nachweis && (
                  // Urheber und Lizenz gehören ins Bild (CC BY/BY-SA): klein, aber lesbar, unten auf dem Foto.
                  <span className="absolute inset-x-0 bottom-0 bg-black/65 px-1.5 py-0.5 text-[8px] leading-tight text-white/85">
                    {e.bild_nachweis}
                  </span>
                )}
              </>
            ) : (
              <span className="font-[family-name:var(--font-akte-titel)] text-6xl text-[#8A94A0]">
                {initialen(e.name)}
              </span>
            )}
          </div>
        ) : null}
        {!fern && (
          <>
            <p className="font-[family-name:var(--font-akte-mono)] text-[10px] uppercase tracking-[0.2em] opacity-60">
              {TYP_NAMEN[e.typ]}
            </p>
            <p
              lang="de"
              className="line-clamp-2 break-words font-[family-name:var(--font-akte-titel)] uppercase leading-[1.05]"
              style={{ fontSize: passendeGroesse(e.name, 26) }}
            >
              {e.name}
            </p>
            {e.kurzbeschreibung && <p className="mt-1 line-clamp-3 text-[13px] leading-snug opacity-75">{e.kurzbeschreibung}</p>}
          </>
        )}
      </div>
      {!data.aufnahme && !fern && !!data.auchIn?.length && data.springen && (
        // Unter der Karte, absolut: die gemessene Kartenhöhe bleibt gleich (sonst rahmt die Aufnahme falsch).
        <div className="nodrag nopan absolute left-0 top-full mt-2 flex w-[260px] flex-wrap gap-1">
          {data.auchIn.slice(0, 4).map((b) => (
            <button
              key={b.slug}
              type="button"
              title={`Auch in „${b.titel}“: dorthin springen`}
              onClick={(ev) => { ev.stopPropagation(); data.springen!(b.slug) }}
              className="flex max-w-[250px] cursor-pointer items-center gap-1 truncate rounded-[3px] border border-[#f0c674]/40 bg-[#101117]/90 px-1.5 py-0.5 font-[family-name:var(--font-akte-mono)] text-[10px] uppercase tracking-wider text-[#f0c674] transition-colors duration-200 hover:border-[#f0c674] hover:bg-[#f0c674]/15"
            >
              <CornerDownRight className="h-3 w-3 shrink-0" aria-hidden />
              <span className="truncate">auch in {b.titel}</span>
            </button>
          ))}
        </div>
      )}
      {data.neu && !data.aufnahme && (
        <span className="akte-neu-stempel pointer-events-none absolute -bottom-3 left-3 z-10 rotate-[-4deg] border-2 border-[#FFD54F] bg-[#0A0A0F] px-1.5 py-0.5 font-[family-name:var(--font-akte-mono)] text-[10px] font-semibold uppercase tracking-[0.25em] text-[#FFD54F]">
          Neu
        </span>
      )}
      {/* Siegel: Ein Mensch hat die Karte mit seinem Schlüssel freigegeben. Nicht in Aufnahme und Render (das Bild
          bleibt wie bisher) und nicht für Leser (die sehen ohnehin nur Unterschriebenes). */}
      {!data.aufnahme && !data.nurLesen && e.status === "freigegeben" && (
        <span className="absolute -left-3 -top-3 z-10 rounded-full shadow-[0_2px_6px_rgba(0,0,0,0.6)]" title="Unterschrieben: ein Mensch hat diese Karte freigegeben">
          <Siegel groesse={28} titel="Unterschrieben" />
        </span>
      )}
      {!data.aufnahme && !data.nurLesen && (data.befunde > 0 || e.status !== "freigegeben") && (
        <span
          title={e.status !== "freigegeben" ? "Entwurf: Karte noch nicht unterschrieben" : `${data.befunde} Faden-Befunde`}
          className="absolute -right-2 -top-2 flex h-6 min-w-6 items-center justify-center gap-0.5 rounded-full bg-[#FFB300] px-1 text-[11px] font-bold text-black"
        >
          <AlertTriangle className="h-3 w-3" aria-hidden />
          {data.befunde > 0 ? data.befunde : ""}
        </span>
      )}
    </div>
  )
})

export type ZettelDaten = {
  zettel: Zettel
  gedimmt: boolean
  deckkraft?: number
  aufnahme: boolean
  speichern: (text: string) => void
}
export type ZettelKnotenTyp = Node<ZettelDaten, "zettel">

const ZETTEL_FARBE: Record<Zettel["art"], string> = {
  notiz: "#EDE6D8",
  meinung: "#FFD54F",
  frage: "#B3E5FC",
}

export const ZettelKnoten = memo(function ZettelKnoten({ data }: NodeProps<ZettelKnotenTyp>) {
  const [bearbeiten, setBearbeiten] = useState(false)
  const [text, setText] = useState(data.zettel.text)
  const z = data.zettel
  return (
    <div
      className="relative w-[200px] p-4 pt-5 text-[15px] leading-snug text-[#141318] shadow-[0_8px_18px_rgba(0,0,0,0.5)] transition-opacity duration-300"
      style={{
        background: ZETTEL_FARBE[z.art],
        opacity: data.deckkraft ?? (data.gedimmt ? 0.12 : 1),
        transform: `rotate(${((z.id * 53) % 7) - 3}deg)`,
        fontFamily: z.art === "meinung" ? "var(--font-akte-text)" : undefined,
      }}
      onDoubleClick={() => !data.aufnahme && setBearbeiten(true)}
    >
      <Nadel farbe={z.art === "meinung" ? "#b8860b" : "#555"} />
      {z.art === "meinung" && (
        <p className="mb-1 font-[family-name:var(--font-akte-mono)] text-[10px] font-semibold uppercase tracking-widest">
          Meine Einschätzung
        </p>
      )}
      {z.art === "frage" && (
        <p className="mb-1 font-[family-name:var(--font-akte-mono)] text-[10px] font-semibold uppercase tracking-widest">
          Offene Frage
        </p>
      )}
      {bearbeiten ? (
        <textarea
          autoFocus
          aria-label="Zettel-Text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={() => {
            setBearbeiten(false)
            if (text !== z.text) data.speichern(text)
          }}
          className="nodrag h-28 w-full resize-none bg-transparent outline-none"
        />
      ) : (
        <p className="whitespace-pre-wrap">{z.text || "Doppelklick zum Schreiben"}</p>
      )}
    </div>
  )
})

export type RahmenDaten = {
  titel: string
  /** Leer = goldene Strichlinie; #RRGGBB = Schild (z. B. „DIE ELITE“ in Rot). */
  farbe?: string
  aufnahme: boolean
  gedimmt: boolean
  deckkraft?: number
  groesse: (x: number, y: number, breite: number, hoehe: number) => void
}
export type RahmenKnotenTyp = Node<RahmenDaten, "rahmen">

export const RahmenKnoten = memo(function RahmenKnoten({ data, selected, width }: NodeProps<RahmenKnotenTyp>) {
  // Der Titel bleibt auf dem Bildschirm mindestens 26 px groß, auch weit herausgezoomt,
  // steht in einer Zeile und passt in die Breite des Rahmens.
  const zoom = useStore((z) => z.transform[2])
  const breite = (width ?? 600) - 40
  const stil = rahmenStil(data.farbe)
  // Die Plakette braucht links und rechts je 0,32 em Rand; sie muss mit in die Breite passen.
  const groesse = Math.min(Math.max(30, 26 / Math.max(zoom, 0.05)), 140, breite / (data.titel.length * 0.48 + (stil.plakette ? 0.64 : 0)))
  return (
    <div
      className="h-full w-full rounded-md transition-opacity duration-300"
      style={{
        border: `${stil.plakette ? 4 : 2}px ${stil.strich} ${stil.rand}`,
        background: stil.flaeche,
        opacity: data.deckkraft ?? (data.gedimmt ? 0.25 : 1),
      }}
    >
      <NodeResizer
        isVisible={selected && !data.aufnahme}
        minWidth={160}
        minHeight={120}
        lineStyle={{ borderColor: FARBEN.gold }}
        handleStyle={{ background: FARBEN.gold, width: 10, height: 10 }}
        onResizeEnd={(_, p) => data.groesse(p.x, p.y, p.width, p.height)}
      />
      <p
        className="absolute left-5 top-3 whitespace-nowrap font-[family-name:var(--font-akte-titel)] uppercase leading-none tracking-wide"
        style={{
          color: stil.titel,
          fontSize: groesse,
          ...(stil.plakette && {
            background: stil.plakette,
            padding: "0.14em 0.32em 0.1em",
            borderRadius: 3,
            boxShadow: "0 6px 18px rgba(0,0,0,0.55)",
          }),
        }}
      >
        {data.titel}
      </p>
    </div>
  )
})

export type BeweisDaten = {
  quelle: Quelle
  gedimmt: boolean
  deckkraft?: number
  aufnahme: boolean
}
export type BeweisKnotenTyp = Node<BeweisDaten, "beweis">

/** Ein Beweisstück: Papier, Vorschaubild, Stempel „GESICHERT“ mit Datum, Herkunft, Prüfsumme. */
export const BeweisKnoten = memo(function BeweisKnoten({ data, selected }: NodeProps<BeweisKnotenTyp>) {
  const q = data.quelle
  const kopie = kopieVon(q)
  const archiv = !!q.archiv_url
  return (
    <div className="relative w-[220px] transition-opacity duration-300" style={{ opacity: data.deckkraft ?? (data.gedimmt ? 0.12 : 1) }}>
      <Nadel farbe={FARBEN.gold} />
      <div
        className="overflow-hidden rounded-[2px] bg-[#EDE6D8] p-2.5 pb-3 text-[#141318] shadow-[0_10px_24px_rgba(0,0,0,0.55)]"
        style={{
          transform: `rotate(${((q.id * 29) % 5) - 2}deg)`,
          outline: selected && !data.aufnahme ? `2px solid ${FARBEN.gold}` : "none",
          outlineOffset: 3,
        }}
      >
        <div className="relative mb-2 flex h-[130px] items-center justify-center overflow-hidden bg-[#d9d0bf]">
          {q.stand?.vorschau ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={akte.dateiUrl(q.stand.vorschau)} alt="" className="h-full w-full object-cover object-top" draggable={false} />
          ) : (
            <FileText className="h-12 w-12 text-[#141318]/40" aria-hidden />
          )}
          <span
            className="absolute bottom-2 right-2 rotate-[-8deg] border-[2.5px] px-1.5 py-0.5 font-[family-name:var(--font-akte-mono)] text-[10px] font-semibold uppercase leading-tight tracking-widest"
            style={{ borderColor: kopie ? "#C8102E" : "#B26B00", color: kopie ? "#C8102E" : "#B26B00", background: "rgba(237,230,216,0.85)" }}
          >
            {kopie ? <>Gesichert<br />{datum(kopie.gesichert_am)}</> : "Nicht gesichert"}
          </span>
        </div>
        <p className="font-[family-name:var(--font-akte-mono)] text-[10px] uppercase tracking-[0.2em] opacity-60">
          Beweisstück {q.guete === "primaer" ? "★" : "☆"}
        </p>
        <p className="line-clamp-3 text-[14px] font-semibold leading-snug">{q.titel}</p>
        <p className="mt-0.5 truncate text-[12px] opacity-70">
          {[q.herausgeber, datum(q.veroeffentlicht_am)].filter(Boolean).join(" · ")}
        </p>
        {!data.aufnahme && (
          <div className="mt-1.5 flex items-center gap-2 text-[11px] opacity-70">
            <span title={kopie ? "Eigene Kopie gesichert" : "Keine eigene Kopie"} className={kopie ? "" : "opacity-30"}>
              <FileText className="inline h-3.5 w-3.5" aria-hidden />
            </span>
            <span title={archiv ? "Bei archive.org hinterlegt" : "Nicht bei archive.org"} className={archiv ? "" : "opacity-30"}>
              <Archive className="inline h-3.5 w-3.5" aria-hidden />
            </span>
            {kopie && (
              <span title={`SHA-256 ${kopie.sha256}`} className="font-[family-name:var(--font-akte-mono)]">
                <Hash className="inline h-3 w-3" aria-hidden />{kopie.sha256.slice(0, 8)}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  )
})

export const knotenTypen = { karte: KarteKnoten, zettel: ZettelKnoten, rahmen: RahmenKnoten, beweis: BeweisKnoten, mappe: MappeKnoten }
