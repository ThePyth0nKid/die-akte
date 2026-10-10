"use client"

// Die Obsidian-Seite einer Karte: Notiz mit [[Links]], Fäden mit Belegen, Rückverweise.

import Link from "next/link"
import { useEffect, useState } from "react"
import { ExternalLink, Pencil, X } from "lucide-react"
import { akte } from "@/lib/akte/api"
import { wikilinks, zeitraum } from "@/lib/akte/faden"
import {
  AUSSAGE_NAMEN, TYP_NAMEN,
  type EntitaetDetail, type EntitaetKurz, type EntitaetTyp, type Quelle, type Status, type Verbindung,
} from "@/lib/akte/typen"
import QuellenVorschau from "./QuellenVorschau"

interface Props {
  id: number
  schliessen: () => void
  geaendert: () => void
  fadenOeffnen: (v: Verbindung) => void
  linkFolgen: (name: string) => void
  karteOeffnen: (e: EntitaetKurz) => void
  anDieWand: (q: Quelle) => void
  zeigen: (q: Quelle, zitat?: string) => void
}

const feld = "min-h-10 w-full rounded border border-[#222636] bg-[#0A0A0F] px-3 text-sm outline-none focus:border-[#f0c674]"
const etikett = "mb-1 block font-[family-name:var(--font-akte-mono)] text-[11px] uppercase tracking-widest text-[#8A94A0]"

export default function NotizLeiste({ id, schliessen, geaendert, fadenOeffnen, linkFolgen, karteOeffnen, anDieWand, zeigen }: Props) {
  const [e, setE] = useState<EntitaetDetail | null>(null)
  const [bearbeiten, setBearbeiten] = useState(false)
  const [entwurf, setEntwurf] = useState<Partial<EntitaetDetail>>({})
  const [fehler, setFehler] = useState("")

  // Der Aufrufer hängt die Leiste je Karte neu ein (key={id}), daher kein Rücksetzen hier.
  useEffect(() => {
    akte.entitaet(id).then((d) => { setE(d); setEntwurf(d) }).catch(() => setFehler("Karte konnte nicht geladen werden."))
  }, [id])

  async function speichern() {
    if (!e) return
    try {
      const { name, typ, kurzbeschreibung, bild_url, notiz_md, oeffentliche_person, status, wikidata_qid } = entwurf
      await akte.entitaetAendern(e.id, { name, typ, kurzbeschreibung, bild_url, notiz_md, oeffentliche_person, status, wikidata_qid })
      setE(await akte.entitaet(e.id))
      setBearbeiten(false)
      setFehler("")
      geaendert()
    } catch (err) {
      setFehler(err instanceof Error ? err.message : "Speichern fehlgeschlagen.")
    }
  }

  const setze = <K extends keyof EntitaetDetail>(k: K, w: EntitaetDetail[K]) => setEntwurf((a) => ({ ...a, [k]: w }))

  return (
    <aside className="absolute bottom-0 right-0 top-0 z-30 flex w-[420px] max-w-full flex-col border-l border-[#222636] bg-[#0d0e14]/95 backdrop-blur" aria-label="Notiz">
      <div className="flex items-center justify-between border-b border-[#222636] px-5 py-3">
        <span className="font-[family-name:var(--font-akte-mono)] text-[11px] uppercase tracking-widest text-[#8A94A0]">
          {e ? TYP_NAMEN[e.typ] : "…"}
        </span>
        <div className="flex gap-1">
          {e && !bearbeiten && (
            <button type="button" onClick={() => setBearbeiten(true)} aria-label="Bearbeiten" className="cursor-pointer p-2 text-[#8A94A0] hover:text-white">
              <Pencil className="h-4 w-4" />
            </button>
          )}
          <button type="button" onClick={schliessen} aria-label="Schließen" className="cursor-pointer p-2 text-[#8A94A0] hover:text-white">
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        {fehler && <p role="alert" className="mb-3 text-sm text-[#FF1744]">{fehler}</p>}
        {!e ? <p className="text-[#8A94A0]">Lädt …</p> : bearbeiten ? (
          <div className="space-y-4">
            <label className="block"><span className={etikett}>Name</span>
              <input className={feld} value={entwurf.name ?? ""} onChange={(ev) => setze("name", ev.target.value)} />
            </label>
            <label className="block"><span className={etikett}>Typ</span>
              <select className={feld} value={entwurf.typ} onChange={(ev) => setze("typ", ev.target.value as EntitaetTyp)}>
                {Object.entries(TYP_NAMEN).map(([k, n]) => <option key={k} value={k}>{n}</option>)}
              </select>
            </label>
            <label className="block"><span className={etikett}>Kurzbeschreibung</span>
              <input className={feld} maxLength={300} value={entwurf.kurzbeschreibung ?? ""} onChange={(ev) => setze("kurzbeschreibung", ev.target.value)} />
            </label>
            <label className="block"><span className={etikett}>Bild (URL)</span>
              <input className={feld} value={entwurf.bild_url ?? ""} onChange={(ev) => setze("bild_url", ev.target.value)} />
            </label>
            <label className="block"><span className={etikett}>Wikidata-ID</span>
              <input className={feld} placeholder="Q…" value={entwurf.wikidata_qid ?? ""} onChange={(ev) => setze("wikidata_qid", ev.target.value)} />
            </label>
            {entwurf.typ === "person" && (
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" className="mt-1" checked={!!entwurf.oeffentliche_person} onChange={(ev) => setze("oeffentliche_person", ev.target.checked)} />
                <span>Person des öffentlichen Lebens (Amt, Macht, öffentliche Rolle). Sonst erscheint sie öffentlich nur mit Initialen.</span>
              </label>
            )}
            <label className="block"><span className={etikett}>Status</span>
              <select className={feld} value={entwurf.status} onChange={(ev) => setze("status", ev.target.value as Status)}>
                <option value="entwurf">Entwurf</option>
                <option value="freigegeben">Freigegeben</option>
              </select>
            </label>
            <label className="block"><span className={etikett}>Notiz (Markdown, [[Name]] verlinkt)</span>
              <textarea className={`${feld} h-64 py-2 font-[family-name:var(--font-akte-mono)] text-[13px]`} value={entwurf.notiz_md ?? ""} onChange={(ev) => setze("notiz_md", ev.target.value)} />
            </label>
            <div className="flex gap-2">
              <button type="button" onClick={speichern} className="min-h-11 flex-1 cursor-pointer rounded bg-[#FF1744] font-semibold text-white">Speichern</button>
              <button type="button" onClick={() => { setEntwurf(e); setBearbeiten(false) }} className="min-h-11 cursor-pointer rounded border border-[#222636] px-4">Abbrechen</button>
            </div>
          </div>
        ) : (
          <>
            <h2 className="font-[family-name:var(--font-akte-titel)] text-4xl uppercase leading-none">{e.name}</h2>
            {e.kurzbeschreibung && <p className="mt-2 text-[#8A94A0]">{e.kurzbeschreibung}</p>}
            {e.status !== "freigegeben" && <p className="mt-2 text-xs text-[#FFB300]">Entwurf: erscheint nicht öffentlich.</p>}
            {e.typ === "person" && !e.oeffentliche_person && (
              <p className="mt-1 text-xs text-[#FFB300]">Privatperson: öffentlich nur als Initialen.</p>
            )}

            {e.notiz_md && (
              <div className="mt-5 whitespace-pre-wrap text-[15px] leading-relaxed">
                {wikilinks(e.notiz_md).map((t, i) =>
                  t.art === "text" ? <span key={i}>{t.text}</span> : (
                    <button key={i} type="button" onClick={() => linkFolgen(t.ziel)}
                      className="cursor-pointer text-[#f0c674] underline decoration-dotted underline-offset-4 hover:text-white">
                      {t.text}
                    </button>
                  ),
                )}
              </div>
            )}

            <h3 className={`${etikett} mt-7`}>Fäden ({e.faeden.length})</h3>
            <ul className="space-y-2">
              {e.faeden.map((v) => {
                const anderer = e.nachbarn.find((n) => n.id === (v.von === e.id ? v.nach : v.von))
                return (
                  <li key={v.id}>
                    <button type="button" onClick={() => fadenOeffnen(v)}
                      className="w-full cursor-pointer rounded border border-[#222636] p-3 text-left transition-colors duration-200 hover:border-[#FF1744]">
                      <span className="flex items-baseline justify-between gap-2">
                        <span className="font-semibold">{v.von === e.id ? "→" : "←"} {anderer?.name ?? "?"}</span>
                        <span className="font-[family-name:var(--font-akte-mono)] text-[11px] text-[#8A94A0]">{zeitraum(v)}</span>
                      </span>
                      <span className="mt-1 block text-sm text-[#8A94A0]">
                        {v.beschreibung || "—"} · {AUSSAGE_NAMEN[v.aussageart]} · {v.belege.length} Beleg{v.belege.length === 1 ? "" : "e"}
                      </span>
                      {v.befunde.length > 0 && (
                        <span className="mt-1 block text-xs text-[#FFB300]">{v.befunde.length} offene Punkte vor Veröffentlichung</span>
                      )}
                    </button>
                    {v.belege.length > 0 && (
                      <div className="mt-1.5 space-y-1.5 pl-3">
                        {v.belege.map((b) => b.quelle_detail && (
                          <QuellenVorschau key={b.quelle} quelle={b.quelle_detail} zitat={b.zitat_woertlich || undefined} anDieWand={anDieWand} zeigen={zeigen} />
                        ))}
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>

            {e.nachbarn.length > 0 && (
              <>
                <h3 className={`${etikett} mt-7`}>Verbunden mit</h3>
                <div className="flex flex-wrap gap-2">
                  {e.nachbarn.map((n) => (
                    <button key={n.id} type="button" onClick={() => karteOeffnen(n)}
                      className="min-h-9 cursor-pointer rounded-full border border-[#222636] px-3 text-sm hover:border-[#f0c674]">
                      {n.name}
                    </button>
                  ))}
                </div>
              </>
            )}

            {!!e.boards?.length && (
              <>
                <h3 className={`${etikett} mt-7`}>Kommt vor in</h3>
                <div className="flex flex-wrap gap-2">
                  {e.boards.map((b) => (
                    <Link key={b.slug} href={`/akte/${b.slug}?${new URLSearchParams({ karte: e.slug }).toString()}`}
                      className="flex min-h-9 items-center rounded-full border border-[#f0c674]/40 px-3 text-sm text-[#f0c674] hover:border-[#f0c674]">
                      {b.titel}
                    </Link>
                  ))}
                </div>
              </>
            )}

            {e.rueckverweise.length > 0 && (
              <>
                <h3 className={`${etikett} mt-7`}>Erwähnt in</h3>
                <div className="flex flex-wrap gap-2">
                  {e.rueckverweise.map((n) => (
                    <button key={n.id} type="button" onClick={() => karteOeffnen(n)}
                      className="min-h-9 cursor-pointer rounded-full border border-[#222636] px-3 text-sm hover:border-[#f0c674]">
                      {n.name}
                    </button>
                  ))}
                </div>
              </>
            )}

            {e.wikidata_qid && (
              <a href={`https://www.wikidata.org/wiki/${e.wikidata_qid}`} target="_blank" rel="noreferrer"
                className="mt-7 inline-flex items-center gap-1 text-sm text-[#8A94A0] hover:text-white">
                Wikidata {e.wikidata_qid} <ExternalLink className="h-3 w-3" aria-hidden />
              </a>
            )}
          </>
        )}
      </div>
    </aside>
  )
}
