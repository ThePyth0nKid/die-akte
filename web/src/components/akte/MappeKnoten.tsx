"use client"

// Die Aktenmappe: ein ganzes Board als Deckel auf der Wand. Doppelklick oder „Öffnen“ führt hinein.
// Feste Größe (560 × 380) in jeder Zoomstufe, sonst rahmt die Aufnahme falsch;
// keine eigenen Uhren, damit der Render deterministisch bleibt.

import { memo } from "react"
import { Handle, Position, useStore, type Node, type NodeProps } from "@xyflow/react"
import { FolderOpen } from "lucide-react"
import { FARBEN } from "@/lib/akte/faden"
import { MAPPE_B, MAPPE_H } from "@/lib/akte/mappen"
import { bildArt } from "@/lib/akte/ordnung"
import type { Mappe } from "@/lib/akte/typen"

export type MappeDaten = {
  mappe: Mappe
  gedimmt: boolean
  /** Im Render-Modus: Deckkraft aus der Zeit, statt CSS-Übergang. */
  deckkraft?: number
  aufnahme: boolean
  papier: boolean
  oeffnen: () => void
}
export type MappeKnotenTyp = Node<MappeDaten, "mappe">

const NUR_TITEL_UNTER = 0.42
const MANILA = "#d9b77a"
const HEX = /^#[0-9a-f]{6}$/i
const MINI_B = 250
const MINI_H = 188

function Miniatur({ m }: { m: Mappe }) {
  const roh = m.vorschau ?? { seitenverhaeltnis: 1, rahmen: [], karten: [] }
  const v = { seitenverhaeltnis: roh.seitenverhaeltnis || 1, rahmen: roh.rahmen ?? [], karten: roh.karten ?? [] }
  const verh = v.seitenverhaeltnis || 1
  const b = verh >= MINI_B / MINI_H ? MINI_B : MINI_H * verh
  const h = verh >= MINI_B / MINI_H ? MINI_B / verh : MINI_H
  return (
    <div className="flex items-center justify-center rounded-[2px] bg-[#15161d] p-2 shadow-inner" style={{ width: MINI_B + 16, height: MINI_H + 16 }}>
      <svg width={b} height={h} viewBox={`0 0 ${b} ${h}`} aria-hidden>
        {v.rahmen.map(([x, y, rb, rh, farbe], i) => (
          <rect key={`r${i}`} x={x * b} y={y * h} width={rb * b} height={rh * h}
            fill={HEX.test(farbe) ? `${farbe}33` : "none"} stroke={HEX.test(farbe) ? farbe : FARBEN.gold}
            strokeWidth={HEX.test(farbe) ? 1.4 : 0.8} strokeDasharray={HEX.test(farbe) ? undefined : "3 2"} />
        ))}
        {v.karten.map(([x, y], i) => (
          <rect key={`k${i}`} x={x * b} y={y * h} width={2.6} height={3.4} fill="#F2F7FB" opacity={0.75} />
        ))}
      </svg>
    </div>
  )
}

function Gesicht({ g }: { g: Mappe["gesichter"][number] }) {
  const art = bildArt(g.bild_nachweis)
  return (
    <figure className="relative h-[92px] w-[92px] overflow-hidden rounded-[2px] bg-[#222636]" title={g.bild_nachweis ? `${g.name} · ${g.bild_nachweis}` : g.name}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={g.bild_url} alt={g.name} draggable={false}
        className={`h-full w-full ${art === "zeichen" ? "bg-[#EDE6D8] object-contain p-2" : art === "unbeschnitten" ? "object-contain" : "object-cover object-top"}`}
        style={{ filter: g.typ === "person" ? "grayscale(0.35) contrast(1.05)" : undefined }} />
      {g.bild_nachweis && (
        // Urheber und Lizenz gehören ins Bild (CC BY/BY-SA), wie auf der Karte.
        <figcaption className="absolute inset-x-0 bottom-0 line-clamp-2 bg-black/70 px-1 text-[6.5px] leading-tight text-white/85">
          {g.bild_nachweis}
        </figcaption>
      )}
    </figure>
  )
}

export const MappeKnoten = memo(function MappeKnoten({ data, selected }: NodeProps<MappeKnotenTyp>) {
  const m = data.mappe
  const fern = useStore((z) => z.transform[2] < NUR_TITEL_UNTER)
  const grund = /^#[0-9a-f]{6}$/i.test(m.farbe ?? "") ? m.farbe : MANILA
  const z = m.zaehler ?? { karten: 0, faeden: 0, quellen: 0 }
  const zaehler = `${z.karten} Karten · ${z.faeden} Fäden · ${z.quellen} Quellen`
  return (
    <div
      className="relative transition-opacity duration-300"
      style={{ width: MAPPE_B, height: MAPPE_H, opacity: data.deckkraft ?? (data.gedimmt ? 0.12 : 1) }}
    >
      <Handle id="nadel" type="source" position={Position.Top} className="akte-nadel" isConnectable={false} />
      {/* Reiter der Mappe */}
      <div aria-hidden className="absolute left-8 top-0 h-9 w-48 -translate-y-7 rounded-t-md" style={{ background: grund, filter: "brightness(0.9)" }} />
      <div
        className="absolute inset-0 overflow-hidden rounded-[4px] text-[#141318] shadow-[0_16px_34px_rgba(0,0,0,0.6)]"
        style={{
          background: `repeating-linear-gradient(0deg, transparent 0 22px, rgba(0,0,0,0.035) 22px 23px), ${grund}`,
          outline: selected && !data.aufnahme ? `3px solid ${FARBEN.gold}` : "none",
          outlineOffset: 4,
        }}
      >
        {/* Stempel */}
        <span aria-hidden
          className="absolute right-6 top-5 rotate-[-9deg] border-[3px] border-[#C8102E] px-2 py-0.5 font-[family-name:var(--font-akte-mono)] text-[15px] font-bold tracking-[0.35em] text-[#C8102E] opacity-80">
          AKTE
        </span>
        {fern ? (
          <div className="flex h-full flex-col justify-center gap-3 px-8">
            <p lang="de" className="break-words font-[family-name:var(--font-akte-titel)] text-[64px] uppercase leading-[0.92]">{m.titel}</p>
            <p className="font-[family-name:var(--font-akte-mono)] text-[22px] uppercase tracking-widest opacity-75">{zaehler}</p>
          </div>
        ) : (
          <div className="flex h-full flex-col px-6 pb-4 pt-5">
            <p className="font-[family-name:var(--font-akte-mono)] text-[11px] font-semibold uppercase tracking-[0.3em] opacity-70">Mappe</p>
            <p lang="de" className="line-clamp-2 max-w-[400px] break-words font-[family-name:var(--font-akte-titel)] text-[32px] uppercase leading-[1]">
              {m.titel}
            </p>
            <div className="mt-3 flex flex-1 gap-4">
              <Miniatur m={m} />
              <div className="grid h-fit grid-cols-2 gap-2">
                {(m.gesichter ?? [])
                  .filter((g) => !(data.aufnahme && /^Platzhalter/i.test(g.bild_nachweis ?? "")))
                  .slice(0, 4).map((g, i) => <Gesicht key={`${g.name}-${i}`} g={g} />)}
              </div>
            </div>
            <div className="mt-2 flex items-center justify-between gap-3">
              <p className="font-[family-name:var(--font-akte-mono)] text-[12px] uppercase tracking-widest opacity-80">{zaehler}</p>
              {!data.aufnahme && (
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); data.oeffnen() }}
                  className="nodrag nopan flex min-h-9 cursor-pointer items-center gap-1.5 rounded-[3px] bg-[#141318] px-3 text-sm font-semibold text-[#F2F7FB] transition-colors duration-200 hover:bg-[#C8102E]"
                >
                  <FolderOpen className="h-4 w-4" aria-hidden /> Öffnen
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
})
