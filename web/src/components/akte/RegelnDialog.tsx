"use client"

// Prüfregeln dieses Boards, Veröffentlichen und die eigenen Schlüssel. Die Prüfung berät, der Mensch entscheidet:
// Jede Regel ist einzeln einstellbar (aus, Hinweis, sperrt). Ob ein Faden freigegeben und seitdem unverändert ist,
// sperrt immer. Vor dem Veröffentlichen sieht der Mensch genau die Lese-Ansicht, samt aller Freitexte – auch solcher,
// die ein Werkzeug geschrieben hat (Rahmen, Beschreibungen).

import { useEffect, useState } from "react"
import { Archive, Globe, KeyRound, X } from "lucide-react"
import { akte, AkteFehler } from "@/lib/akte/api"
import { eigeneSchluessel, hierGespeichert, widerrufen, type EigenerSchluessel } from "@/lib/akte/unterschrift"
import { useEigeneAnfrage } from "./EigeneAnfrage"
import type { Regel, Stufe, Wand } from "@/lib/akte/typen"

const STUFEN: { wert: Stufe; name: string }[] = [
  { wert: "aus", name: "aus" },
  { wert: "hinweis", name: "Hinweis" },
  { wert: "sperrt", name: "sperrt" },
]

type Schluessel = EigenerSchluessel & { hier: boolean }

/** Alles, was Leser als Text zu sehen bekommen, ohne Karten- und Fadeninhalte (die hat ein Mensch unterschrieben). */
function freitexte(w: Wand): { wo: string; text: string }[] {
  const liste = [{ wo: "Titel", text: w.board.titel }, { wo: "Beschreibung", text: w.board.beschreibung }]
  for (const r of w.rahmen) liste.push({ wo: "Rahmen", text: r.titel })
  for (const z of w.zettel) liste.push({ wo: "Meinungs-Zettel", text: z.text })
  for (const m of w.mappen ?? []) liste.push({ wo: "Mappe", text: [m.titel, m.beschreibung].filter(Boolean).join(" – ") })
  return liste.filter((t) => t.text && t.text.trim())
}

export default function RegelnDialog({ slug, oeffentlich, schliessen, geaendert }: {
  slug: string
  oeffentlich: boolean
  schliessen: () => void
  geaendert: () => void
}) {
  const [regeln, setRegeln] = useState<Regel[] | null>(null)
  const [wahl, setWahl] = useState<Record<string, Stufe>>({})
  const [schluessel, setSchluessel] = useState<Schluessel[]>([])
  const [meldung, setMeldung] = useState("")
  const [laeuft, setLaeuft] = useState(false)
  const [vorschau, setVorschau] = useState<Wand | null>(null)
  const [istOeffentlich, setIstOeffentlich] = useState(oeffentlich)
  // Für die ganze Akte: archive.org. null = noch nicht geladen; Fehlertext, wenn der Server die Einstellung nicht kennt.
  const [archiv, setArchiv] = useState<boolean | null>(null)
  const [archivMeldung, setArchivMeldung] = useState("")
  const [archivLaeuft, setArchivLaeuft] = useState(false)
  // Änderungen melden sich bei der Wand an: Die Live-Aktualisierung zeigt sie nicht als „neu“.
  const eigene = useEigeneAnfrage()

  async function vorschauLaden() {
    setLaeuft(true)
    try {
      setVorschau(await akte.lesevorschau(slug))
    } catch (e) {
      setMeldung(e instanceof Error ? e.message : "Vorschau nicht lesbar.")
    } finally {
      setLaeuft(false)
    }
  }

  async function oeffentlichSetzen(an: boolean) {
    const frage = an
      ? "Dieses Board jetzt öffentlich schalten? Besucher ohne Konto sehen genau die Vorschau oben, " +
        "sofern die Akte Lesen ohne Konto erlaubt (AKTE_OEFFENTLICH_AKTIV)."
      : "Dieses Board nicht mehr öffentlich zeigen?"
    if (!window.confirm(frage)) return
    setLaeuft(true)
    try {
      await eigene(() => akte.boardAendern(slug, { oeffentlich: an }))
      setIstOeffentlich(an)
      setMeldung(an ? "Öffentlich." : "Nicht mehr öffentlich.")
      geaendert()
    } catch (e) {
      setMeldung(e instanceof Error ? e.message : "Umschalten fehlgeschlagen.")
    } finally {
      setLaeuft(false)
    }
  }

  async function schluesselLaden() {
    const liste = await eigeneSchluessel()
    setSchluessel(await Promise.all(liste.map(async (s) => ({ ...s, hier: await hierGespeichert(s.kid) }))))
  }

  useEffect(() => {
    akte.pruefung(slug)
      .then((p) => { setRegeln(p.regeln); setWahl(Object.fromEntries(p.regeln.map((r) => [r.code, r.stufe]))) })
      .catch((e) => setMeldung(e instanceof Error ? e.message : "Regeln nicht lesbar."))
    schluesselLaden().catch(() => setSchluessel([]))
    akte.einstellungen()
      .then((e) => setArchiv(Boolean(e.archiv_org)))
      .catch((e) => setArchivMeldung(e instanceof AkteFehler && e.status === 404
        ? "Diese Version der Akte kennt die Einstellung noch nicht. Bitte die Akte aktualisieren."
        : e instanceof AkteFehler && e.status === 403
          ? "Diese Einstellung darf nur die Redaktion ändern."
          : "Die Einstellung konnte nicht gelesen werden."))
  }, [slug])

  async function archivSetzen(an: boolean) {
    const vorher = archiv
    setArchiv(an)
    setArchivLaeuft(true)
    setArchivMeldung("")
    try {
      const e = await eigene(() => akte.einstellungenAendern({ archiv_org: an }))
      setArchiv(Boolean(e.archiv_org))
      setArchivMeldung(e.archiv_org
        ? "Gespeichert: Quellen landen jetzt zusätzlich öffentlich bei archive.org; ältere werden im Hintergrund nachgesichert."
        : "Gespeichert: Neue Quellen bleiben nur in deiner Akte.")
    } catch {
      setArchiv(vorher)
      setArchivMeldung("Speichern fehlgeschlagen. Die Einstellung ist unverändert.")
    } finally {
      setArchivLaeuft(false)
    }
  }

  useEffect(() => {
    const taste = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); schliessen() } }
    window.addEventListener("keydown", taste, true)
    return () => window.removeEventListener("keydown", taste, true)
  }, [schliessen])

  async function speichern(neu: Record<string, Stufe>) {
    setLaeuft(true)
    setMeldung("")
    try {
      await eigene(() => akte.boardAendern(slug, { regeln: neu }))
      const p = await akte.pruefung(slug)
      setRegeln(p.regeln)
      setWahl(Object.fromEntries(p.regeln.map((r) => [r.code, r.stufe])))
      setMeldung("Gespeichert. Die Prüfung dieses Boards gilt ab sofort mit diesen Stufen.")
      geaendert()
    } catch (e) {
      setMeldung(e instanceof AkteFehler || e instanceof Error ? e.message : "Speichern fehlgeschlagen.")
    } finally {
      setLaeuft(false)
    }
  }

  async function widerruf(s: Schluessel) {
    const text = `Schlüssel ${s.fingerabdruck} widerrufen?\n\nAlles, was er später unterschreibt, ist ungültig. ` +
      "Frühere Unterschriften bleiben gültig. Der Widerruf steht unterschrieben in der Kette."
    if (!window.confirm(text)) return
    setLaeuft(true)
    try {
      await eigene(() => widerrufen(s.kid))
      await schluesselLaden()
      setMeldung("Widerrufen.")
    } catch (e) {
      setMeldung(e instanceof Error ? e.message : "Widerruf fehlgeschlagen.")
    } finally {
      setLaeuft(false)
    }
  }

  const geaendertGegenStand = regeln?.some((r) => wahl[r.code] !== r.stufe) ?? false

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 pt-[8vh]"
      onMouseDown={schliessen}>
      <div role="dialog" aria-label="Regeln, Veröffentlichen und Schlüssel" onMouseDown={(e) => e.stopPropagation()}
        className="w-full max-w-2xl rounded-lg border border-[#222636] bg-[#0d0e14] p-5 text-[#F2F7FB] shadow-2xl">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Regeln und Veröffentlichen</h2>
          <button type="button" onClick={schliessen} aria-label="Schließen" className="rounded p-2 hover:bg-white/10">
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mb-4 text-sm text-[#8A94A0]">
          Die Prüfung berät, du entscheidest. <b>Hinweis</b> zeigt einen Befund, hält aber nichts auf. <b>sperrt</b> hält
          einen Faden aus der Lese-Ansicht, bis du ihn bei der Freigabe mit Begründung überstimmst. Freigegeben und seit
          der Unterschrift unverändert muss ein Faden immer sein.
        </p>
        {!regeln && !meldung && <p className="text-sm text-[#8A94A0]">Lade …</p>}
        {regeln && (
          <table className="mb-4 w-full text-sm">
            <tbody>
              {regeln.map((r) => (
                <tr key={r.code} className="border-t border-[#222636]">
                  <td className="py-2 pr-3">
                    {r.text}
                    {wahl[r.code] !== r.standard && (
                      <span className="ml-2 text-xs text-[#8A94A0]">(Standard: {r.standard})</span>
                    )}
                  </td>
                  <td className="py-2 text-right">
                    <select aria-label={r.text} value={wahl[r.code] ?? r.stufe} disabled={laeuft}
                      onChange={(e) => setWahl((w) => ({ ...w, [r.code]: e.target.value as Stufe }))}
                      className="min-h-9 rounded border border-[#222636] bg-[#0A0A0F] px-2">
                      {STUFEN.map((s) => <option key={s.wert} value={s.wert}>{s.name}</option>)}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {regeln && (
          <div className="mb-6 flex flex-wrap gap-2">
            <button type="button" disabled={laeuft || !geaendertGegenStand} onClick={() => speichern(wahl)}
              className="min-h-10 rounded-md bg-[#f0c674] px-4 text-sm font-semibold text-[#0A0A0F] disabled:opacity-40">
              Speichern
            </button>
            <button type="button" disabled={laeuft} onClick={() => speichern({})}
              className="min-h-10 rounded-md px-4 text-sm text-[#8A94A0] hover:bg-white/10">
              Auf Standard zurücksetzen
            </button>
          </div>
        )}

        <h3 className="mb-2 flex items-center gap-2 font-semibold"><Globe className="h-4 w-4" /> Veröffentlichen</h3>
        <p className="mb-2 text-sm text-[#8A94A0]">
          {istOeffentlich ? "Dieses Board ist öffentlich." : "Dieses Board ist nicht öffentlich."} Leser sehen nur Karten
          und Fäden, die ein Mensch unterschrieben hat. Titel, Beschreibung, Rahmen, Meinungs-Zettel und Mappen
          erscheinen dagegen so, wie sie sind – prüfe sie in der Vorschau.
        </p>
        <div className="mb-3 flex flex-wrap gap-2">
          <button type="button" disabled={laeuft} onClick={vorschauLaden}
            className="min-h-10 rounded-md border border-[#222636] px-4 text-sm hover:bg-white/10">
            Vorschau für Besucher
          </button>
          {istOeffentlich ? (
            <button type="button" disabled={laeuft} onClick={() => oeffentlichSetzen(false)}
              className="min-h-10 rounded-md px-4 text-sm text-[#FF1744] hover:bg-[#FF1744]/10">
              Nicht mehr öffentlich
            </button>
          ) : (
            <button type="button" disabled={laeuft || !vorschau} onClick={() => oeffentlichSetzen(true)}
              title={vorschau ? "" : "Erst die Vorschau ansehen"}
              className="min-h-10 rounded-md bg-[#f0c674] px-4 text-sm font-semibold text-[#0A0A0F] disabled:opacity-40">
              Öffentlich schalten
            </button>
          )}
        </div>
        {vorschau && (
          <div className="mb-6 rounded border border-[#222636] p-3 text-sm" aria-label="Vorschau für Besucher">
            <p className="mb-2">
              {vorschau.karten.length} Karten, {vorschau.faeden.length} Fäden
              {vorschau.mappen?.length ? `, ${vorschau.mappen.length} Mappen` : ""} sichtbar.
            </p>
            <ul className="space-y-1">
              {freitexte(vorschau).map((t, i) => (
                <li key={i}><span className="text-[#8A94A0]">{t.wo}:</span> {t.text}</li>
              ))}
            </ul>
          </div>
        )}

        <h3 className="mb-2 flex items-center gap-2 font-semibold"><KeyRound className="h-4 w-4" /> Deine Schlüssel</h3>
        <p className="mb-2 text-sm text-[#8A94A0]">
          Mit ihnen unterschreibst du Freigaben. Der private Teil liegt nur im Browser, in dem er entstanden ist. Ein
          verlorenes Gerät: Schlüssel hier widerrufen.
        </p>
        {schluessel.length === 0 && <p className="text-sm text-[#8A94A0]">Noch keiner; die erste Freigabe legt ihn an.</p>}
        <ul className="space-y-1 text-sm">
          {schluessel.map((s) => (
            <li key={s.kid} className="flex items-center justify-between gap-3 border-t border-[#222636] py-2">
              <span className="font-[family-name:var(--font-akte-mono)]">
                {s.fingerabdruck}
                {s.hier && <span className="ml-2 text-xs text-[#f0c674]">in diesem Browser</span>}
                {s.widerrufen_am && <span className="ml-2 text-xs text-[#FF1744]">widerrufen</span>}
              </span>
              {!s.widerrufen_am && (
                <button type="button" disabled={laeuft} onClick={() => widerruf(s)}
                  className="min-h-9 rounded-md px-3 text-xs text-[#FF1744] hover:bg-[#FF1744]/10">
                  Widerrufen
                </button>
              )}
            </li>
          ))}
        </ul>

        <h3 className="mb-2 mt-6 flex items-center gap-2 border-t border-[#222636] pt-5 font-semibold">
          <Archive className="h-4 w-4" aria-hidden /> Für die ganze Akte
        </h3>
        <div className="flex items-start justify-between gap-4">
          <div>
            <p id="archiv-titel" className="text-sm">Quellen zusätzlich öffentlich bei archive.org sichern</p>
            <p id="archiv-erklaerung" className="mt-1 text-sm text-[#8A94A0]">
              Dann liegt eine öffentliche Kopie jeder Quelle bei archive.org – gut als Beweis, aber andere sehen, was du
              sicherst. Beim Einschalten werden ältere Quellen im Hintergrund nachgesichert. Was schon bei archive.org
              liegt, bleibt dort. Deine eigene Kopie in der Akte entsteht immer.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={archiv === true}
            aria-labelledby="archiv-titel"
            aria-describedby="archiv-erklaerung"
            disabled={archiv === null || archivLaeuft}
            onClick={() => archiv !== null && archivSetzen(!archiv)}
            className={`relative mt-0.5 inline-flex h-7 w-12 shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#f0c674] disabled:cursor-not-allowed disabled:opacity-40 ${archiv ? "border-[#FF1744] bg-[#FF1744]" : "border-[#222636] bg-[#0A0A0F]"}`}
          >
            <span aria-hidden className={`inline-block h-5 w-5 rounded-full bg-[#F2F7FB] shadow transition-transform duration-200 ${archiv ? "translate-x-6" : "translate-x-1"}`} />
          </button>
        </div>
        <p className="mt-1 font-[family-name:var(--font-akte-mono)] text-[11px] uppercase tracking-widest text-[#8A94A0]" aria-hidden>
          {archiv === null ? "" : archiv ? "An" : "Aus"}
        </p>
        {archivMeldung && <p role="status" className="mt-2 text-sm text-[#f0c674]">{archivMeldung}</p>}

        {meldung && <p role="status" className="mt-4 text-sm text-[#f0c674]">{meldung}</p>}
      </div>
    </div>
  )
}
