"use client"

// Lese-Ansicht für Mitglieder: Karte und Faden aus den Wanddaten, ohne weiteren Abruf.
// Keine Notizen, kein Bearbeiten, keine Sicherungen — nur, was an der Wand steht, mit Quelle.

import { X } from "lucide-react"
import { zeitraum } from "@/lib/akte/faden"
import { bildArt, type BildArt } from "@/lib/akte/ordnung"
import { TYP_NAMEN, VERBINDUNG_NAMEN, type BoardVerweis, type EntitaetKurz, type Verbindung } from "@/lib/akte/typen"
import QuellenVorschau from "./QuellenVorschau"

const etikett = "mb-1 block font-[family-name:var(--font-akte-mono)] text-[11px] uppercase tracking-widest text-[#8A94A0]"

const BILD_KLASSE: Record<BildArt, string> = {
  zeichen: "bg-[#EDE6D8] object-contain p-4",
  unbeschnitten: "object-contain",
  fuellend: "object-cover object-top",
}

function Belege({ v }: { v: Verbindung }) {
  return (
    <div className="mt-1.5 space-y-1.5 pl-3">
      {v.belege.map((b) => b.quelle_detail && (
        <QuellenVorschau key={b.id ?? b.quelle} quelle={b.quelle_detail} zitat={b.zitat_woertlich || undefined} nurLesen />
      ))}
    </div>
  )
}

export function KarteLesen({ karte, faeden, namen, schliessen, karteOeffnen, auchIn = [], springen }: {
  karte: EntitaetKurz
  faeden: Verbindung[]
  namen: Map<number, EntitaetKurz>
  schliessen: () => void
  karteOeffnen: (e: EntitaetKurz) => void
  /** Andere freigeschaltete Wände mit derselben Karte (Portale). */
  auchIn?: BoardVerweis[]
  springen?: (slug: string) => void
}) {
  const eigene = faeden.filter((v) => !v.ausgeblendet && (v.von === karte.id || v.nach === karte.id))
  return (
    <aside className="absolute bottom-0 right-0 top-0 z-30 flex w-[420px] max-w-full flex-col border-l border-[#222636] bg-[#0d0e14]/95 backdrop-blur" aria-label="Karte">
      <div className="flex items-center justify-between border-b border-[#222636] px-5 py-3">
        <span className={etikett}>{TYP_NAMEN[karte.typ]}</span>
        <button type="button" onClick={schliessen} aria-label="Schließen" className="flex h-10 w-10 cursor-pointer items-center justify-center rounded hover:bg-white/10">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-5">
        {karte.bild_url && (
          <figure className="mb-4">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={karte.bild_url}
              alt={karte.name}
              // Wie auf der Karte: Zeichen ganz auf hellem Grund, CC BY-SA / BY-ND unbeschnitten, sonst füllend.
              className={`max-h-64 w-full rounded ${BILD_KLASSE[bildArt(karte.bild_nachweis)]}`}
              loading="lazy"
            />
            {karte.bild_nachweis && <figcaption className="mt-1 text-[11px] text-[#8A94A0]">{karte.bild_nachweis}</figcaption>}
          </figure>
        )}
        <h2 className="font-[family-name:var(--font-akte-titel)] text-4xl uppercase leading-none">{karte.name}</h2>
        {karte.kurzbeschreibung && <p className="mt-2 text-[#8A94A0]">{karte.kurzbeschreibung}</p>}

        {auchIn.length > 0 && springen && (
          <>
            <h3 className={`${etikett} mt-6`}>Kommt vor in</h3>
            <div className="flex flex-wrap gap-2">
              {auchIn.map((b) => (
                <button key={b.slug} type="button" onClick={() => springen(b.slug)}
                  className="min-h-9 cursor-pointer rounded-full border border-[#f0c674]/40 px-3 text-sm text-[#f0c674] hover:border-[#f0c674]">
                  {b.titel}
                </button>
              ))}
            </div>
          </>
        )}

        <h3 className={`${etikett} mt-7`}>Verbindungen ({eigene.length})</h3>
        <ul className="space-y-3">
          {eigene.map((v) => {
            const andererId = v.von === karte.id ? v.nach : v.von
            const anderer = namen.get(andererId)
            return (
              <li key={v.id}>
                <div className="rounded border border-[#222636] p-3">
                  <span className="flex items-baseline justify-between gap-2">
                    <button type="button" disabled={!anderer} onClick={() => anderer && karteOeffnen(anderer)}
                      className="cursor-pointer text-left font-semibold hover:text-[#f0c674]">
                      {v.von === karte.id ? "→" : "←"} {anderer?.name ?? "?"}
                    </button>
                    <span className="font-[family-name:var(--font-akte-mono)] text-[11px] text-[#8A94A0]">{zeitraum(v)}</span>
                  </span>
                  <span className="mt-1 block text-sm text-[#8A94A0]">
                    {v.beschreibung || VERBINDUNG_NAMEN[v.typ]} · {v.belege.length} Beleg{v.belege.length === 1 ? "" : "e"}
                  </span>
                </div>
                <Belege v={v} />
              </li>
            )
          })}
        </ul>
      </div>
    </aside>
  )
}

export function FadenLesen({ v, von, nach, schliessen }: {
  v: Verbindung
  von?: EntitaetKurz
  nach?: EntitaetKurz
  schliessen: () => void
}) {
  return (
    <div role="dialog" aria-modal="true" aria-label="Verbindung" className="absolute inset-0 z-40 flex items-center justify-center bg-black/60 p-4" onClick={schliessen}>
      <div className="max-h-[85vh] w-[560px] max-w-full overflow-y-auto rounded-lg border border-[#222636] bg-[#0d0e14] p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <span className={etikett}>{VERBINDUNG_NAMEN[v.typ]} · {zeitraum(v)}</span>
            <h2 className="font-[family-name:var(--font-akte-titel)] text-3xl uppercase leading-tight">
              {von?.name ?? "?"} → {nach?.name ?? "?"}
            </h2>
            {v.beschreibung && <p className="mt-1 text-[#8A94A0]">{v.beschreibung}</p>}
          </div>
          <button type="button" onClick={schliessen} aria-label="Schließen" className="flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded hover:bg-white/10">
            <X className="h-4 w-4" />
          </button>
        </div>
        <h3 className={`${etikett} mt-5`}>Belege</h3>
        <Belege v={v} />
      </div>
    </div>
  )
}
