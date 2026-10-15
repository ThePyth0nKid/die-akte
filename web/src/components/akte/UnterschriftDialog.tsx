"use client"

// Unterschreiben verständlich: Vor der Unterschrift sieht der Mensch in Klartext, was er bestätigt – Von, Nach, Art der
// Verbindung, Aussage, Zeitraum, jeden Beleg mit Quelle und Zitat, offene Hinweise in Worten. Unterschrieben werden
// weiterhin genau die Bytes, die der Server vorbereitet hat (lib/akte/unterschrift.ts); dieser Dialog ist nur die Frage.

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { AlertTriangle, ExternalLink, X } from "lucide-react"
import { belegeKlartext, hinweisKlartext, sichtbarMachen, unterschriftFelder } from "@/lib/akte/klartext"
import {
  HINWEIS_VEROEFFENTLICHUNG, zusammenfassung, type FehlendeBegruendung, type Vorbereitung,
} from "@/lib/akte/unterschrift"
import Siegel from "./Siegel"

type Objekt = "karte" | "faden"

type Anfrage =
  | { art: "bestaetigen"; objekt: Objekt; v: Vorbereitung; fertig: (ok: boolean) => void }
  | { art: "begruendung"; objekt: Objekt; befund: FehlendeBegruendung; fertig: (grund: string | null) => void }

export type Rueckfragen = {
  begruendung: (befund: FehlendeBegruendung) => Promise<string | null>
  bestaetigen: (v: Vorbereitung) => Promise<boolean>
}

/**
 * Rückfragen für `freigebenMitUnterschrift` als eigener Dialog. `fragen(objekt)` liefert die beiden Fragen, `dialog`
 * gehört irgendwo in den Baum. Wird die Komponente abgebaut, gilt eine offene Frage als „Abbrechen“.
 */
export function useUnterschrift(): { fragen: (objekt: Objekt) => Rueckfragen; dialog: React.ReactNode; offen: boolean } {
  const [anfrage, setAnfrage] = useState<Anfrage | null>(null)
  const offenRef = useRef<Anfrage | null>(null)

  useEffect(() => () => {
    const a = offenRef.current
    offenRef.current = null
    if (a?.art === "bestaetigen") a.fertig(false)
    else if (a?.art === "begruendung") a.fertig(null)
  }, [])

  const fragen = useCallback((objekt: Objekt): Rueckfragen => ({
    begruendung: (befund) => new Promise<string | null>((ok) => {
      const a: Anfrage = { art: "begruendung", objekt, befund, fertig: ok }
      offenRef.current = a
      setAnfrage(a)
    }),
    bestaetigen: (v) => new Promise<boolean>((ok) => {
      const a: Anfrage = { art: "bestaetigen", objekt, v, fertig: ok }
      offenRef.current = a
      setAnfrage(a)
    }),
  }), [])

  const schliessen = useCallback((antwort: boolean | string | null) => {
    const a = offenRef.current
    offenRef.current = null
    setAnfrage(null)
    if (a?.art === "bestaetigen") a.fertig(antwort === true)
    else if (a?.art === "begruendung") a.fertig(typeof antwort === "string" ? antwort : null)
  }, [])

  // Über ein Portal in die Wurzel der Akte: Die Notiz-Leiste hat einen Weichzeichner im Hintergrund, und darin wäre ein
  // „fixed“-Dialog auf die Breite der Leiste eingesperrt. In der Wurzel gelten weiter die Schriften der Akte.
  const dialog = useMemo(() => {
    if (!anfrage || typeof document === "undefined") return null
    const ziel = document.getElementById("akte-wurzel") ?? document.body
    return createPortal(<UnterschriftDialog anfrage={anfrage} antworten={schliessen} />, ziel)
  }, [anfrage, schliessen])
  return { fragen, dialog, offen: !!anfrage }
}

const etikett = "font-[family-name:var(--font-akte-mono)] text-[11px] uppercase tracking-widest text-[#8A94A0]"

function UnterschriftDialog({ anfrage, antworten }: { anfrage: Anfrage; antworten: (a: boolean | string | null) => void }) {
  const kasten = useRef<HTMLDivElement>(null)
  const titel = useRef<HTMLHeadingElement>(null)
  const [grund, setGrund] = useState("")
  const [hinweis, setHinweis] = useState("")

  // Fokus in den Dialog (auf die Überschrift, nicht auf „Unterschreiben“: Enter soll nicht aus Versehen unterschreiben)
  // und beim Schließen zurück, wo er war.
  useEffect(() => {
    const vorher = document.activeElement as HTMLElement | null
    titel.current?.focus()
    // Ein Bild später: Der auslösende Knopf ist während der Freigabe gesperrt und erst danach wieder fokussierbar.
    return () => { requestAnimationFrame(() => { if (vorher?.isConnected) vorher.focus() }) }
  }, [])

  function taste(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.stopPropagation()
      antworten(anfrage.art === "bestaetigen" ? false : null)
      return
    }
    if (e.key !== "Tab" || !kasten.current) return
    // Fokus bleibt im Dialog.
    const ziele = [...kasten.current.querySelectorAll<HTMLElement>(
      "a[href], button:not([disabled]), textarea, input, summary, [tabindex]:not([tabindex='-1'])",
    )]
    if (!ziele.length) return
    const erstes = ziele[0]
    const letztes = ziele[ziele.length - 1]
    if (e.shiftKey && (document.activeElement === erstes || document.activeElement === titel.current)) {
      e.preventDefault()
      letztes.focus()
    } else if (!e.shiftKey && document.activeElement === letztes) {
      e.preventDefault()
      erstes.focus()
    }
  }

  const istBestaetigen = anfrage.art === "bestaetigen"
  const ueberschrift = istBestaetigen
    ? (anfrage.objekt === "faden" ? "Diesen Faden unterschreiben?" : "Diese Karte unterschreiben?")
    : "Begründung nötig"

  return (
    <div
      className="fixed inset-0 z-[70] flex items-start justify-center overflow-y-auto bg-black/75 p-4 sm:pt-[6vh]"
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div
        ref={kasten}
        role={istBestaetigen ? "alertdialog" : "dialog"}
        aria-modal="true"
        aria-labelledby="unterschrift-titel"
        aria-describedby="unterschrift-erklaerung"
        onKeyDown={taste}
        className="w-full max-w-2xl rounded-lg border border-[#222636] bg-[#0d0e14] text-[#F2F7FB] shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-[#222636] px-5 py-4">
          <div className="flex items-center gap-3">
            <Siegel groesse={34} />
            <h2 ref={titel} id="unterschrift-titel" tabIndex={-1}
              className="font-[family-name:var(--font-akte-titel)] text-3xl uppercase leading-none tracking-wide outline-none">
              {ueberschrift}
            </h2>
          </div>
          <button type="button" aria-label="Abbrechen" onClick={() => antworten(istBestaetigen ? false : null)}
            className="flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded text-[#8A94A0] hover:bg-white/10 hover:text-white focus-visible:outline-2 focus-visible:outline-[#f0c674]">
            <X className="h-5 w-5" />
          </button>
        </div>

        {anfrage.art === "bestaetigen" ? (
          <Bestaetigen anfrage={anfrage} />
        ) : (
          <div className="space-y-4 px-5 py-5">
            <p id="unterschrift-erklaerung" className="text-sm leading-relaxed text-[#C9CED6]">
              Eine Regel dieses Boards hält die Freigabe auf. Du kannst sie überstimmen, musst aber sagen, warum.
            </p>
            <div className="flex gap-3 rounded-md border border-[#FFB300]/50 bg-[#FFB300]/10 p-3 text-sm">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[#FFB300]" aria-hidden />
              <div>
                <p className="font-semibold">{hinweisKlartext(anfrage.befund.code, anfrage.befund.text)}</p>
                {anfrage.befund.text && anfrage.befund.text !== hinweisKlartext(anfrage.befund.code, anfrage.befund.text) && (
                  <p className="mt-1 text-[#C9CED6]">{sichtbarMachen(anfrage.befund.text)}</p>
                )}
              </div>
            </div>
            <label className="block">
              <span className={`${etikett} mb-1.5 block`}>Warum gibst du trotzdem frei?</span>
              <textarea value={grund} onChange={(e) => { setGrund(e.target.value); setHinweis("") }} rows={4} maxLength={2000}
                aria-describedby="begruendung-hinweis" aria-invalid={!!hinweis}
                className="w-full rounded-md border border-[#222636] bg-[#0A0A0F] px-3 py-2 text-sm outline-none focus:border-[#f0c674]" />
            </label>
            <p id="begruendung-hinweis" className="text-xs text-[#8A94A0]">{HINWEIS_VEROEFFENTLICHUNG}</p>
            {hinweis && <p role="alert" className="text-sm text-[#FF6B85]">{hinweis}</p>}
          </div>
        )}

        <div className="flex flex-wrap justify-end gap-3 border-t border-[#222636] px-5 py-4">
          <button type="button" onClick={() => antworten(istBestaetigen ? false : null)}
            className="min-h-11 cursor-pointer rounded-md border border-[#222636] px-5 text-sm hover:bg-white/10 focus-visible:outline-2 focus-visible:outline-[#f0c674]">
            Abbrechen
          </button>
          {istBestaetigen ? (
            <button type="button" onClick={() => antworten(true)}
              className="flex min-h-11 cursor-pointer items-center gap-2 rounded-md bg-[#FF1744] px-5 font-semibold text-white hover:bg-[#ff3d63] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#f0c674]">
              Mit meinem Schlüssel unterschreiben
            </button>
          ) : (
            <button type="button"
              onClick={() => (grund.trim() ? antworten(grund.trim()) : setHinweis("Bitte schreib eine kurze Begründung."))}
              className="min-h-11 cursor-pointer rounded-md bg-[#f0c674] px-5 font-semibold text-[#0A0A0F] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#f0c674]">
              Weiter
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function Bestaetigen({ anfrage }: { anfrage: Extract<Anfrage, { art: "bestaetigen" }> }) {
  const { v, objekt } = anfrage
  const felder = unterschriftFelder(objekt, v.inhalt)
  const belege = objekt === "faden" ? belegeKlartext(v.inhalt) : []
  return (
    <div className="max-h-[62vh] space-y-5 overflow-y-auto px-5 py-5">
      <p id="unterschrift-erklaerung" className="text-sm leading-relaxed text-[#C9CED6]">
        Prüf in Ruhe, was du bestätigst. Mit der Unterschrift sagst du: Das stimmt, und die Belege tragen es. Sie steht
        danach dauerhaft in der Kette der Akte.
      </p>

      <dl className="grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-4 gap-y-2 rounded-md border border-[#222636] p-4 text-sm">
        {felder.map((f) => (
          <div key={f.name} className="contents">
            <dt className={`${etikett} pt-0.5`}>{f.name}</dt>
            <dd className="break-words">{f.wert}</dd>
          </div>
        ))}
      </dl>

      {objekt === "faden" && (
        <section aria-labelledby="belege-titel">
          <h3 id="belege-titel" className={`${etikett} mb-2`}>
            Belege ({belege.length})
          </h3>
          {belege.length === 0 && <p className="text-sm text-[#FFB300]">Kein Beleg. Ohne Quelle trägt der Faden nichts.</p>}
          <ol className="space-y-3">
            {belege.map((b, i) => (
              <li key={i} className="rounded-md border border-[#222636] p-3 text-sm">
                <p className="font-semibold">
                  <span className="mr-1" title={b.primaer ? "Original geöffnet" : "Presse / Sekundär"}>{b.primaer ? "★" : "☆"}</span>
                  {b.titel}
                  {b.herausgeber && <span className="font-normal text-[#8A94A0]"> · {b.herausgeber}</span>}
                </p>
                {b.url && (b.link ? (
                  <a href={b.link} target="_blank" rel="noopener noreferrer"
                    className="mt-0.5 inline-flex max-w-full items-center gap-1 break-all text-xs text-[#f0c674] underline decoration-dotted underline-offset-2">
                    {b.url} <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
                  </a>
                ) : (
                  // Kein http/https oder versteckte Zeichen: nur als Text, nie als anklickbarer Link.
                  <span className="mt-0.5 block break-all text-xs text-[#FFB300]">{b.url} (kein sicherer Link)</span>
                ))}
                {b.host && (
                  <p className="mt-0.5 text-xs text-[#8A94A0]">
                    Server: <span className="font-[family-name:var(--font-akte-mono)] text-[#F2F7FB]">{b.host}</span>
                  </p>
                )}
                {b.linkWarnungen.map((w) => (
                  <p key={w} role="note" className="mt-1 flex gap-1.5 text-xs text-[#FFB300]">
                    <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden /> {w}
                  </p>
                ))}
                <blockquote className="mt-2 border-l-2 border-[#FF1744] pl-3 leading-relaxed">
                  {b.zitat ? `„${b.zitat}“` : <span className="text-[#FFB300]">Kein wörtliches Zitat.</span>}
                </blockquote>
                <p className="mt-2 text-xs text-[#8A94A0]">
                  {[
                    b.fundstelle && `Fundstelle: ${b.fundstelle}`,
                    b.kopie ? `Eigene Kopie gesichert (Prüfsumme ${b.kopie} …)` : "Noch keine eigene Kopie gesichert",
                    b.archivUrl && (b.archivLink ? "Archivkopie bei archive.org" : `Archivadresse: ${b.archivUrl}`),
                  ].filter(Boolean).join(" · ")}
                </p>
              </li>
            ))}
          </ol>
        </section>
      )}

      {v.hinweise_offen.length > 0 && (
        <section aria-labelledby="hinweise-titel" className="rounded-md border border-[#FFB300]/50 bg-[#FFB300]/10 p-4 text-sm">
          <h3 id="hinweise-titel" className="mb-1 flex items-center gap-2 font-semibold text-[#FFB300]">
            <AlertTriangle className="h-4 w-4" aria-hidden /> Offene Hinweise
          </h3>
          <p className="mb-2 text-[#C9CED6]">Sie halten nichts auf. Du kannst trotzdem unterschreiben.</p>
          <ul className="list-disc space-y-1 pl-5">
            {v.hinweise_offen.map((code) => <li key={code}>{hinweisKlartext(code)}</li>)}
          </ul>
        </section>
      )}

      {v.ueberstimmungen.length > 0 && (
        <section aria-labelledby="ueberstimmt-titel" className="rounded-md border border-[#FF1744]/40 p-4 text-sm">
          <h3 id="ueberstimmt-titel" className="mb-2 font-semibold">Du überstimmst</h3>
          <ul className="space-y-2">
            {v.ueberstimmungen.map((u) => (
              <li key={u.code}>
                <p>{hinweisKlartext(u.code)}</p>
                <p className="text-[#8A94A0]">Deine Begründung: „{sichtbarMachen(u.begruendung)}“</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      <p className="text-xs text-[#8A94A0]">{HINWEIS_VEROEFFENTLICHUNG}</p>

      <details className="rounded-md border border-[#222636] text-xs">
        <summary className="cursor-pointer px-3 py-2 text-[#8A94A0] hover:text-white">
          Angaben des Servers
        </summary>
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words px-3 pb-3 font-[family-name:var(--font-akte-mono)] text-[11px] leading-relaxed text-[#C9CED6]">
          {sichtbarMachen(zusammenfassung(v))}
        </pre>
      </details>
    </div>
  )
}
