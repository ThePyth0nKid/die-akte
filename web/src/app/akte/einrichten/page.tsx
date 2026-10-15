"use client"

// Erstes Konto im Browser: Einrichtungscode aus dem Starter, Benutzername, Passwort, und die Frage nach archive.org.
// Ein Agent kann kein verdecktes Passwort eingeben (und soll es nicht): Das Konto legt immer der Mensch hier an.

import Link from "next/link"
import { useEffect, useRef, useState } from "react"
import { Eye, EyeOff } from "lucide-react"
import {
  codeAnzeigen, codeAusFragment, einrichtungDaten, einrichtungFehler, einrichtungPruefen, einrichtungZustand, PASSWORT_MIN,
  type EinrichtungEingabe, type EinrichtungFeld, type EinrichtungZustand, type FeldFehler,
} from "@/lib/einrichtung"

const etikett = "mb-1.5 block font-[family-name:var(--font-akte-mono)] text-[11px] uppercase tracking-widest text-[#8A94A0]"
const feldKlasse = (fehler?: string) =>
  `min-h-11 w-full rounded-md border bg-[#0A0A0F] px-3 text-[15px] outline-none transition-colors duration-200 focus:border-[#f0c674] ${fehler ? "border-[#FF1744]" : "border-[#222636]"}`

const REIHENFOLGE: EinrichtungFeld[] = ["code", "benutzername", "passwort", "wiederholung"]

export default function Einrichten() {
  const [zustand, setZustand] = useState<EinrichtungZustand | "laedt">("laedt")
  const [eingabe, setEingabe] = useState<EinrichtungEingabe>({
    code: "", benutzername: "", passwort: "", wiederholung: "", archivOrg: false,
  })
  const [felder, setFelder] = useState<FeldFehler>({})
  const [meldung, setMeldung] = useState("")
  const [schonEingerichtet, setSchonEingerichtet] = useState(false)
  const [laeuft, setLaeuft] = useState(false)
  const [zeigen, setZeigen] = useState(false)
  const refs = useRef<Partial<Record<EinrichtungFeld, HTMLInputElement | null>>>({})
  const meldungRef = useRef<HTMLParagraphElement>(null)
  const codeVorbelegt = useRef(false)
  const [vorbelegt, setVorbelegt] = useState(false)

  // Der Starter öffnet die Seite mit `#code=…` (das Fragment geht nie an einen Server). Code ins Feld, sichtbar und
  // änderbar, und das Fragment sofort aus der Adresse löschen: nicht im Verlauf, nicht beim Teilen des Links.
  useEffect(() => {
    const code = codeAusFragment(window.location.hash)
    if (window.location.hash) {
      window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search)
    }
    if (code) {
      codeVorbelegt.current = true
      // Das Fragment gibt es nur im Browser; beim Vorab-Rendern auf dem Server ist es unbekannt.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setEingabe((alt) => ({ ...alt, code }))
      setVorbelegt(true)
    }
  }, [])

  useEffect(() => {
    const ac = new AbortController()
    einrichtungZustand(ac.signal).then(setZustand).catch(() => undefined)
    return () => ac.abort()
  }, [])

  // Steht der Code schon drin, geht es mit dem Benutzernamen weiter.
  useEffect(() => {
    if (zustand === "offen" && codeVorbelegt.current) refs.current.benutzername?.focus()
  }, [zustand])

  function nochmal() {
    setZustand("laedt")
    einrichtungZustand().then(setZustand).catch(() => undefined)
  }

  const setze = <K extends keyof EinrichtungEingabe>(k: K, w: EinrichtungEingabe[K]) => {
    setEingabe((alt) => ({ ...alt, [k]: w }))
    if (k in felder) setFelder((alt) => ({ ...alt, [k]: undefined }))
  }

  async function absenden(e: React.FormEvent) {
    e.preventDefault()
    setMeldung("")
    setSchonEingerichtet(false)
    const lokal = einrichtungPruefen(eingabe)
    const erstes = REIHENFOLGE.find((f) => lokal[f])
    if (erstes) {
      setFelder(lokal)
      refs.current[erstes]?.focus()
      return
    }
    setFelder({})
    setLaeuft(true)
    try {
      const res = await fetch("/api/auth/einrichtung", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(einrichtungDaten(eingabe)),
      })
      const daten = (await res.json().catch(() => ({}))) as { angemeldet?: boolean }
      if (res.status === 201) {
        // Ganze Seite neu: Cookies und Konto-Knopf stimmen sofort.
        window.location.assign(daten.angemeldet ? "/akte" : "/login?redirect=%2Fakte&neu=1")
        return
      }
      zeigeFehler(res.status, daten)
    } catch {
      zeigeFehler(0, null)
    }
  }

  function zeigeFehler(status: number, daten: unknown) {
    const a = einrichtungFehler(status, daten)
    setFelder(a.felder)
    setMeldung(a.meldung)
    setSchonEingerichtet(a.schonEingerichtet)
    setLaeuft(false)
    const erstes = REIHENFOLGE.find((f) => a.felder[f])
    // Feld mit Fehler zuerst, sonst die Meldung: Wer mit Tastatur oder Vorleser arbeitet, landet beim Problem.
    requestAnimationFrame(() => (erstes ? refs.current[erstes]?.focus() : meldungRef.current?.focus()))
  }

  const beschreibung = (f: EinrichtungFeld, hilfe?: string) =>
    [felder[f] ? `${f}-fehler` : "", hilfe ?? ""].filter(Boolean).join(" ") || undefined

  return (
    <main className="h-full overflow-y-auto px-5 py-10 sm:px-6 sm:py-14">
      <div className="mx-auto max-w-xl">
        <p className="font-[family-name:var(--font-akte-mono)] text-xs uppercase tracking-[0.3em] text-[#8A94A0]">
          Erster Start
        </p>
        <h1 className="font-[family-name:var(--font-akte-titel)] text-5xl uppercase leading-none tracking-wide sm:text-6xl">
          Ultra-Akte einrichten
        </h1>

        {zustand === "laedt" && <p className="mt-8 text-[#8A94A0]" role="status">Prüfe, ob die Akte schon ein Konto hat …</p>}

        {zustand === "unerreichbar" && (
          <div className="mt-8 rounded-lg border border-[#FF1744]/50 bg-[#FF1744]/10 p-5" role="alert">
            <p>Die Ultra-Akte antwortet gerade nicht oder ist beschäftigt. Warte einen Moment und prüf noch einmal. Läuft sie
              nicht, starte sie neu (START-AKTE).</p>
            <button type="button" onClick={nochmal}
              className="mt-4 min-h-11 cursor-pointer rounded-md border border-[#222636] px-4 text-sm hover:bg-white/10 focus-visible:outline-2 focus-visible:outline-[#f0c674]">
              Noch einmal prüfen
            </button>
          </div>
        )}

        {zustand === "zu" && (
          <div className="mt-8 rounded-lg border border-[#222636] bg-[#0d0e14] p-5">
            <p className="text-lg">Die Ultra-Akte ist schon eingerichtet.</p>
            <p className="mt-1 text-sm text-[#8A94A0]">Melde dich mit deinem Konto an.</p>
            <div className="mt-4 flex flex-wrap gap-3">
              <Link href="/login?redirect=%2Fakte"
                className="inline-flex min-h-11 items-center rounded-md bg-[#f0c674] px-5 font-semibold text-[#0A0A0F] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#f0c674]">
                Anmelden
              </Link>
              <Link href="/akte" className="inline-flex min-h-11 items-center rounded-md border border-[#222636] px-5 text-sm hover:bg-white/10">
                Zur Übersicht
              </Link>
            </div>
          </div>
        )}

        {zustand === "kein_code" && (
          <div className="mt-8 rounded-lg border border-[#FFB300]/50 bg-[#FFB300]/10 p-5">
            <p className="text-lg">Die Einrichtung im Browser ist aus.</p>
            <p className="mt-2 text-sm leading-relaxed text-[#C9CED6]">
              Diese Akte hat keinen Einrichtungscode. Den legt der Starter beim Start an (START-AKTE). Ohne Starter
              legst du das erste Konto im Terminal an, im Ordner der Akte:
            </p>
            <pre className="mt-3 overflow-x-auto rounded-md border border-[#222636] bg-[#0A0A0F] p-3 font-[family-name:var(--font-akte-mono)] text-sm">
              <code>docker compose exec api python manage.py akte_einrichten</code>
            </pre>
            <p className="mt-2 text-xs text-[#8A94A0]">Der Befehl fragt nach Benutzername und Passwort. Danach hier anmelden.</p>
            <Link href="/login?redirect=%2Fakte"
              className="mt-4 inline-flex min-h-11 items-center rounded-md bg-[#f0c674] px-5 font-semibold text-[#0A0A0F] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#f0c674]">
              Anmelden
            </Link>
          </div>
        )}

        {zustand === "offen" && (
          <>
            <p className="mt-4 max-w-prose leading-relaxed text-[#C9CED6]">
              Lege dein Konto an. Damit legst du Wände an und unterschreibst Freigaben. Den Einrichtungscode trägt der
              Starter ein, wenn er diese Seite öffnet. Ein KI-Agent kennt ihn nicht und fragt nie danach.
            </p>
            <form onSubmit={absenden} noValidate aria-describedby="einrichten-hinweis"
              className="mt-8 space-y-6 rounded-lg border border-[#222636] bg-[#0d0e14] p-5 sm:p-6">
              {meldung && (
                <p ref={meldungRef} tabIndex={-1} role="alert"
                  className="rounded-md border border-[#FF1744]/50 bg-[#FF1744]/10 p-3 text-sm outline-none">
                  {meldung}
                  {schonEingerichtet && (
                    <> <Link href="/login?redirect=%2Fakte" className="font-semibold text-[#f0c674] underline">Zum Anmelden</Link></>
                  )}
                </p>
              )}

              <div>
                <label htmlFor="code" className={etikett}>Einrichtungscode</label>
                <input
                  id="code" ref={(el) => { refs.current.code = el }}
                  value={eingabe.code} onChange={(e) => setze("code", codeAnzeigen(e.target.value))}
                  placeholder="ABCD-EF23" autoComplete="off" autoCapitalize="characters" spellCheck={false}
                  aria-invalid={!!felder.code} aria-describedby={beschreibung("code", "code-hilfe")}
                  className={`${feldKlasse(felder.code)} font-[family-name:var(--font-akte-mono)] text-lg tracking-[0.3em]`}
                />
                <p id="code-hilfe" className="mt-1 text-xs text-[#8A94A0]">
                  {vorbelegt && eingabe.code
                    ? "Vom Starter eingetragen. Du kannst ihn ändern."
                    : "8 Zeichen. Der Starter trägt ihn ein, wenn er den Browser öffnet; fehlt er, starte START-AKTE noch einmal."}
                </p>
                {felder.code && <p id="code-fehler" className="mt-1 text-sm text-[#FF6B85]">{felder.code}</p>}
              </div>

              <div>
                <label htmlFor="benutzername" className={etikett}>Benutzername</label>
                <input
                  id="benutzername" ref={(el) => { refs.current.benutzername = el }}
                  value={eingabe.benutzername} onChange={(e) => setze("benutzername", e.target.value)}
                  autoComplete="username" autoCapitalize="none" spellCheck={false} maxLength={150}
                  aria-invalid={!!felder.benutzername} aria-describedby={beschreibung("benutzername")}
                  className={feldKlasse(felder.benutzername)}
                />
                {felder.benutzername && <p id="benutzername-fehler" className="mt-1 text-sm text-[#FF6B85]">{felder.benutzername}</p>}
              </div>

              <div>
                <div className="flex items-end justify-between gap-3">
                  <label htmlFor="passwort" className={etikett}>Passwort</label>
                  <button type="button" onClick={() => setZeigen((z) => !z)} aria-pressed={zeigen}
                    className="mb-1 flex min-h-8 cursor-pointer items-center gap-1.5 rounded px-2 text-xs text-[#8A94A0] hover:text-white focus-visible:outline-2 focus-visible:outline-[#f0c674]">
                    {zeigen ? <EyeOff className="h-3.5 w-3.5" aria-hidden /> : <Eye className="h-3.5 w-3.5" aria-hidden />}
                    {zeigen ? "Passwort verbergen" : "Passwort zeigen"}
                  </button>
                </div>
                <input
                  id="passwort" ref={(el) => { refs.current.passwort = el }}
                  type={zeigen ? "text" : "password"}
                  value={eingabe.passwort} onChange={(e) => setze("passwort", e.target.value)}
                  autoComplete="new-password"
                  aria-invalid={!!felder.passwort} aria-describedby={beschreibung("passwort", "passwort-hilfe")}
                  className={feldKlasse(felder.passwort)}
                />
                <p id="passwort-hilfe" className="mt-1 text-xs text-[#8A94A0]">
                  Mindestens {PASSWORT_MIN} Zeichen, nicht nur Ziffern, kein bekanntes Allerweltspasswort.
                </p>
                {felder.passwort && <p id="passwort-fehler" className="mt-1 text-sm text-[#FF6B85]">{felder.passwort}</p>}
              </div>

              <div>
                <label htmlFor="wiederholung" className={etikett}>Passwort wiederholen</label>
                <input
                  id="wiederholung" ref={(el) => { refs.current.wiederholung = el }}
                  type={zeigen ? "text" : "password"}
                  value={eingabe.wiederholung} onChange={(e) => setze("wiederholung", e.target.value)}
                  autoComplete="new-password"
                  aria-invalid={!!felder.wiederholung} aria-describedby={beschreibung("wiederholung")}
                  className={feldKlasse(felder.wiederholung)}
                />
                {felder.wiederholung && <p id="wiederholung-fehler" className="mt-1 text-sm text-[#FF6B85]">{felder.wiederholung}</p>}
              </div>

              <fieldset aria-describedby="archiv-erklaerung">
                <legend className="text-[15px] font-semibold">Quellen zusätzlich öffentlich bei archive.org sichern?</legend>
                <p id="archiv-erklaerung" className="mt-1 text-sm leading-relaxed text-[#8A94A0]">
                  Dann liegt eine öffentliche Kopie jeder Quelle bei archive.org – gut als Beweis, aber andere sehen, was
                  du sicherst. Deine eigene Kopie in der Akte entsteht so oder so. Du kannst das später unter „Regeln“ ändern.
                </p>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  {[
                    { wert: false, titel: "Nein", text: "Nur in meiner Akte" },
                    { wert: true, titel: "Ja", text: "Zusätzlich öffentlich bei archive.org" },
                  ].map((w) => (
                    <label key={String(w.wert)}
                      className={`flex min-h-11 cursor-pointer items-center gap-3 rounded-md border px-3 py-2 text-sm transition-colors duration-200 focus-within:ring-2 focus-within:ring-[#f0c674] ${eingabe.archivOrg === w.wert ? "border-[#FF1744] bg-[#FF1744]/10" : "border-[#222636] hover:border-[#8A94A0]"}`}>
                      <input type="radio" name="archiv" className="h-4 w-4 accent-[#FF1744]"
                        checked={eingabe.archivOrg === w.wert} onChange={() => setze("archivOrg", w.wert)} />
                      <span><b>{w.titel}</b> – {w.text}</span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <button type="submit" disabled={laeuft}
                className="flex min-h-12 w-full cursor-pointer items-center justify-center rounded-md bg-[#FF1744] px-5 text-base font-semibold text-white transition-colors duration-200 hover:bg-[#ff3d63] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#f0c674] disabled:cursor-wait disabled:opacity-60">
                {laeuft ? "Lege Konto an …" : "Konto anlegen und loslegen"}
              </button>
              <p id="einrichten-hinweis" className="text-xs leading-relaxed text-[#8A94A0]">
                Das Passwort geht nur an deine Akte, nicht an Claude und an keinen anderen Dienst. Ein KI-Agent tippt hier
                nie etwas ein: Das Konto legst du selbst an.
              </p>
            </form>
          </>
        )}
      </div>
    </main>
  )
}
