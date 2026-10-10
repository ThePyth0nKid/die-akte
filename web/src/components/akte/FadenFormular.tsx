"use client"

// Einen Faden anlegen oder ändern — mit Zeitraum, Aussageart und Belegen.
// Die Prüfung im Backend sagt nach dem Speichern, was vor der Veröffentlichung fehlt.

import { useEffect, useState } from "react"
import { Plus, Trash2, X } from "lucide-react"
import { akte } from "@/lib/akte/api"
import {
  AUSSAGE_NAMEN, VERBINDUNG_NAMEN,
  type Aussageart, type Beleg, type EntitaetKurz, type Quelle, type Status, type Verbindung, type VerbindungTyp,
} from "@/lib/akte/typen"

interface Props {
  von: EntitaetKurz
  nach: EntitaetKurz
  vorhanden?: Verbindung
  fertig: (v: Verbindung | null) => void
}

const heute = () => new Date().toISOString().slice(0, 10)

const feld = "min-h-10 w-full rounded border border-[#222636] bg-[#0A0A0F] px-3 text-sm outline-none focus:border-[#f0c674]"
const etikett = "mb-1 block font-[family-name:var(--font-akte-mono)] text-[11px] uppercase tracking-widest text-[#8A94A0]"

type NeueQuelle = Pick<Quelle, "url" | "titel" | "herausgeber" | "abgerufen_am" | "archiv_url" | "guete">

export default function FadenFormular({ von, nach, vorhanden, fertig }: Props) {
  const [v, setV] = useState({
    typ: (vorhanden?.typ ?? "amt") as VerbindungTyp,
    beschreibung: vorhanden?.beschreibung ?? "",
    start: vorhanden?.start ?? "",
    ende: vorhanden?.ende ?? "",
    aktuell: vorhanden?.aktuell ?? false,
    betrag: vorhanden?.betrag ?? "",
    waehrung: vorhanden?.waehrung ?? "",
    aussageart: (vorhanden?.aussageart ?? "belegt") as Aussageart,
    konfidenz: vorhanden?.konfidenz ?? 2,
    anhoerung_angefragt_am: vorhanden?.anhoerung_angefragt_am ?? "",
    anhoerung_antwort: vorhanden?.anhoerung_antwort ?? "",
    anhoerung_antwort_am: vorhanden?.anhoerung_antwort_am ?? "",
    status: (vorhanden?.status ?? "entwurf") as Status,
  })
  const [belege, setBelege] = useState<Beleg[]>(vorhanden?.belege ?? [])
  const [suche, setSuche] = useState("")
  const [quellen, setQuellen] = useState<Quelle[]>([])
  const [neu, setNeu] = useState<NeueQuelle | null>(null)
  const [fehler, setFehler] = useState("")
  const [laeuft, setLaeuft] = useState(false)

  useEffect(() => {
    if (!suche.trim()) return
    const t = setTimeout(() => akte.quellenSuchen(suche).then(setQuellen).catch(() => setQuellen([])), 200)
    return () => clearTimeout(t)
  }, [suche])
  const treffer = suche.trim() ? quellen : []

  const setze = <K extends keyof typeof v>(k: K, w: (typeof v)[K]) => setV((alt) => ({ ...alt, [k]: w }))

  async function dateienAnhaengen(dateien: File[]) {
    for (const datei of dateien) {
      try {
        belegDazu(await akte.quelleAusDatei(datei))
      } catch {
        setFehler("Nur PDF oder Bild, höchstens 15 MB.")
      }
    }
  }

  function belegDazu(q: Quelle) {
    if (belege.some((b) => b.quelle === q.id)) return
    setBelege((b) => [...b, { quelle: q.id, quelle_detail: q, zitat_woertlich: "", fundstelle: "" }])
    setSuche("")
  }

  async function neueQuelleSpeichern() {
    if (!neu?.titel.trim()) return
    try {
      const q = await akte.quelleAnlegen({ ...neu, abgerufen_am: neu.abgerufen_am || null })
      belegDazu(q)
      setNeu(null)
    } catch (err) {
      setFehler(err instanceof Error ? err.message : "Quelle konnte nicht angelegt werden.")
    }
  }

  async function speichern(e: React.FormEvent) {
    e.preventDefault()
    setLaeuft(true)
    setFehler("")
    const daten = {
      ...v,
      von: von.id,
      nach: nach.id,
      start: v.start || null,
      ende: v.ende || null,
      betrag: v.betrag || null,
      anhoerung_angefragt_am: v.anhoerung_angefragt_am || null,
      anhoerung_antwort_am: v.anhoerung_antwort_am || null,
      belege: belege.map(({ quelle, zitat_woertlich, fundstelle }) => ({ quelle, zitat_woertlich, fundstelle })),
    }
    try {
      const ergebnis = vorhanden ? await akte.fadenAendern(vorhanden.id, daten) : await akte.fadenAnlegen(daten)
      fertig(ergebnis)
    } catch (err) {
      setFehler(err instanceof Error ? err.message : "Speichern fehlgeschlagen.")
      setLaeuft(false)
    }
  }

  const verdacht = v.aussageart === "verdacht"

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Faden bearbeiten"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onMouseDown={() => fertig(null)}
      onKeyDown={(e) => { if (e.key === "Escape") fertig(null) }}
    >
      <form
        onSubmit={speichern}
        onMouseDown={(e) => e.stopPropagation()}
        className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-lg border border-[#222636] bg-[#101117] p-6 shadow-2xl"
        aria-label="Faden"
      >
        <div className="mb-5 flex items-start justify-between gap-4">
          <h2 className="font-[family-name:var(--font-akte-titel)] text-3xl uppercase leading-tight">
            {von.name} <span className="text-[#FF1744]">→</span> {nach.name}
          </h2>
          <button type="button" onClick={() => fertig(null)} aria-label="Schließen" className="cursor-pointer p-2 text-[#8A94A0] hover:text-white">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <label><span className={etikett}>Art der Verbindung</span>
            <select className={feld} value={v.typ} onChange={(e) => setze("typ", e.target.value as VerbindungTyp)}>
              {Object.entries(VERBINDUNG_NAMEN).map(([k, n]) => <option key={k} value={k}>{n}</option>)}
            </select>
          </label>
          <label><span className={etikett}>Beschriftung am Faden</span>
            <input className={feld} value={v.beschreibung} maxLength={300} placeholder="z. B. Mitgründer"
              onChange={(e) => setze("beschreibung", e.target.value)} />
          </label>
          <label><span className={etikett}>Von (Datum)</span>
            <input type="date" className={feld} value={v.start} onChange={(e) => setze("start", e.target.value)} />
          </label>
          <label><span className={etikett}>Bis (Datum)</span>
            <input type="date" className={feld} value={v.ende} disabled={v.aktuell} onChange={(e) => setze("ende", e.target.value)} />
          </label>
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <input type="checkbox" checked={v.aktuell} onChange={(e) => { setze("aktuell", e.target.checked); if (e.target.checked) setze("ende", "") }} />
            Besteht heute noch
          </label>
          {v.typ === "finanzierung" && (
            <>
              <label><span className={etikett}>Betrag</span>
                <input className={feld} inputMode="decimal" value={v.betrag} onChange={(e) => setze("betrag", e.target.value)} />
              </label>
              <label><span className={etikett}>Währung</span>
                <input className={feld} maxLength={3} value={v.waehrung} placeholder="EUR" onChange={(e) => setze("waehrung", e.target.value.toUpperCase())} />
              </label>
            </>
          )}
        </div>

        <fieldset className="mt-5">
          <legend className={etikett}>Was behauptet der Faden?</legend>
          <div className="flex gap-2">
            {(Object.keys(AUSSAGE_NAMEN) as Aussageart[]).map((a) => (
              <button key={a} type="button" onClick={() => setze("aussageart", a)}
                className={`min-h-10 flex-1 cursor-pointer rounded border px-3 text-sm transition-colors duration-200 ${v.aussageart === a ? "border-[#FF1744] bg-[#FF1744]/15" : "border-[#222636]"}`}>
                {AUSSAGE_NAMEN[a]}
              </button>
            ))}
          </div>
          {v.aussageart === "meinung" && (
            <p className="mt-2 text-xs text-[#8A94A0]">Meinung wird als „Meine Einschätzung“ gekennzeichnet und braucht trotzdem eine Tatsachengrundlage mit Quelle.</p>
          )}
        </fieldset>

        {verdacht && (
          <div className="mt-4 grid gap-4 rounded border border-[#FF1744]/40 p-4 sm:grid-cols-2">
            <p className="text-xs text-[#8A94A0] sm:col-span-2">
              Verdacht gegen eine Person geht nur mit Anhörung und zwei unabhängigen Quellen raus. Die Antwort wird mit angezeigt.
            </p>
            <label><span className={etikett}>Anhörung angefragt am</span>
              <input type="date" className={feld} value={v.anhoerung_angefragt_am} onChange={(e) => setze("anhoerung_angefragt_am", e.target.value)} />
            </label>
            <label><span className={etikett}>Antwort am</span>
              <input type="date" className={feld} value={v.anhoerung_antwort_am} onChange={(e) => setze("anhoerung_antwort_am", e.target.value)} />
            </label>
            <label className="sm:col-span-2"><span className={etikett}>Antwort (wörtlich)</span>
              <textarea className={`${feld} h-20 py-2`} value={v.anhoerung_antwort} onChange={(e) => setze("anhoerung_antwort", e.target.value)} />
            </label>
          </div>
        )}

        <section className="mt-6">
          <h3 className={etikett}>Belege</h3>
          <label
            onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) e.preventDefault() }}
            onDrop={(e) => { e.preventDefault(); dateienAnhaengen([...e.dataTransfer.files]) }}
            className="mb-3 block cursor-pointer rounded border border-dashed border-[#222636] px-3 py-2 text-center text-xs text-[#8A94A0] transition-colors duration-200 focus-within:border-[#f0c674] hover:border-[#f0c674]"
          >
            PDF oder Screenshot hierher ziehen oder klicken: wird gesichert und als Beleg angehängt
            <input
              type="file"
              multiple
              accept="application/pdf,image/png,image/jpeg,image/webp,image/gif"
              className="sr-only"
              onChange={(e) => { const d = [...(e.target.files ?? [])]; e.target.value = ""; dateienAnhaengen(d) }}
            />
          </label>
          <ul className="space-y-3">
            {belege.map((b, i) => (
              <li key={b.quelle} className="rounded border border-[#222636] p-3">
                <div className="mb-2 flex items-start justify-between gap-2">
                  <p className="text-sm">
                    <span className="mr-1">{b.quelle_detail?.guete === "primaer" ? "★" : "☆"}</span>
                    <strong>{b.quelle_detail?.titel ?? `Quelle ${b.quelle}`}</strong>
                    {b.quelle_detail?.herausgeber && <span className="text-[#8A94A0]"> · {b.quelle_detail.herausgeber}</span>}
                  </p>
                  <button type="button" aria-label="Beleg entfernen" className="cursor-pointer p-1 text-[#8A94A0] hover:text-[#FF1744]"
                    onClick={() => setBelege((alt) => alt.filter((_, j) => j !== i))}>
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
                <textarea aria-label="Zitat wörtlich" placeholder="Zitat, wörtlich" className={`${feld} h-16 py-2`} value={b.zitat_woertlich}
                  onChange={(e) => setBelege((alt) => alt.map((x, j) => j === i ? { ...x, zitat_woertlich: e.target.value } : x))} />
                <input aria-label="Fundstelle" placeholder="Fundstelle (Seite, Absatz, Zeitmarke)" className={`${feld} mt-2`} value={b.fundstelle}
                  onChange={(e) => setBelege((alt) => alt.map((x, j) => j === i ? { ...x, fundstelle: e.target.value } : x))} />
              </li>
            ))}
          </ul>

          <div className="relative mt-3">
            <input aria-label="Vorhandene Quelle suchen" placeholder="Vorhandene Quelle suchen …" className={feld} value={suche} onChange={(e) => setSuche(e.target.value)} />
            {treffer.length > 0 && (
              <ul className="absolute z-10 mt-1 max-h-48 w-full overflow-y-auto rounded border border-[#222636] bg-[#0A0A0F]">
                {treffer.map((q) => (
                  <li key={q.id}>
                    <button type="button" onClick={() => belegDazu(q)} className="w-full cursor-pointer px-3 py-2 text-left text-sm hover:bg-[#FF1744]/15">
                      {q.titel} <span className="text-[#8A94A0]">· {q.herausgeber}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {neu ? (
            <div className="mt-3 grid gap-3 rounded border border-[#f0c674]/40 p-3 sm:grid-cols-2">
              <input aria-label="Titel" placeholder="Titel *" className={`${feld} sm:col-span-2`} value={neu.titel} onChange={(e) => setNeu({ ...neu, titel: e.target.value })} />
              <input aria-label="Link" placeholder="https://…" className={`${feld} sm:col-span-2`} value={neu.url} onChange={(e) => setNeu({ ...neu, url: e.target.value })} />
              <input aria-label="Herausgeber" placeholder="Herausgeber (z. B. Bundestag, Spiegel)" className={feld} value={neu.herausgeber} onChange={(e) => setNeu({ ...neu, herausgeber: e.target.value })} />
              <input aria-label="Abgerufen am" type="date" className={feld} value={neu.abgerufen_am ?? ""} onChange={(e) => setNeu({ ...neu, abgerufen_am: e.target.value })} />
              <input aria-label="Archivkopie" placeholder="Archivkopie (web.archive.org/…)" className={`${feld} sm:col-span-2`} value={neu.archiv_url} onChange={(e) => setNeu({ ...neu, archiv_url: e.target.value })} />
              <select aria-label="Güte" className={feld} value={neu.guete} onChange={(e) => setNeu({ ...neu, guete: e.target.value as Quelle["guete"] })}>
                <option value="primaer">★ Original geöffnet</option>
                <option value="sekundaer">☆ Presse / Sekundär</option>
              </select>
              <div className="flex gap-2">
                <button type="button" onClick={neueQuelleSpeichern} className="min-h-10 flex-1 cursor-pointer rounded bg-[#f0c674] px-3 text-sm font-semibold text-black">Quelle anlegen</button>
                <button type="button" onClick={() => setNeu(null)} className="min-h-10 cursor-pointer rounded border border-[#222636] px-3 text-sm">Abbrechen</button>
              </div>
            </div>
          ) : (
            <button type="button" className="mt-3 flex cursor-pointer items-center gap-2 text-sm text-[#f0c674]"
              onClick={() => setNeu({ url: "", titel: "", herausgeber: "", abgerufen_am: heute(), archiv_url: "", guete: "sekundaer" })}>
              <Plus className="h-4 w-4" aria-hidden /> Neue Quelle
            </button>
          )}
        </section>

        <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-[#222636] pt-4">
          <label className="flex items-center gap-2 text-sm">
            <span className={etikett + " mb-0"}>Status</span>
            <select className={`${feld} w-auto`} value={v.status} onChange={(e) => setze("status", e.target.value as Status)}>
              <option value="entwurf">Entwurf</option>
              <option value="freigegeben">Freigegeben</option>
            </select>
          </label>
          <button type="submit" disabled={laeuft} className="min-h-11 cursor-pointer rounded bg-[#FF1744] px-6 font-semibold text-white disabled:opacity-40">
            {laeuft ? "Speichert …" : "Faden speichern"}
          </button>
        </div>
        {fehler && <p role="alert" className="mt-3 text-sm text-[#FF1744]">{fehler}</p>}
        {vorhanden && vorhanden.befunde.length > 0 && (
          <ul className="mt-4 space-y-1 rounded border border-[#FFB300]/40 p-3 text-xs text-[#FFB300]">
            <li className="font-semibold">Noch nicht veröffentlichbar:</li>
            {vorhanden.befunde.map((b) => <li key={b.code + b.text}>· {b.text}</li>)}
          </ul>
        )}
      </form>
    </div>
  )
}
