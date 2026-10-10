#!/usr/bin/env node
// Rendert eine Fahrt der Akte als schnittfertiges Video: Bild für Bild (25 fps) aus der
// Render-Ansicht /akte/<board>/render, nach ffmpeg (H.264, CRF 16, yuv420p, +faststart, ohne Ton),
// dazu ein Standbild je Station. Kein Echtzeit-Mitschnitt: das Bild ist eine reine Funktion der Zeit.
//
//   node render/render_fahrt.cjs --board musterhafen --fahrt 3 --titel "Kapitel 1" \
//        --formate 16x9,9x16 [--halte 3000] [--look papier] [--stichworte] [--legende] [--4k] [--unschaerfe]
//        [--basis http://127.0.0.1:8080] [--ziel <ordner>] [--name <dateiname>] [--zeiten zeiten.json]
//
// --zeiten: {stationen: [Satzanfang je Station in ms], ende_ms} aus render/vertonen.py — dann fährt die
// Kamera im Takt der Stimme (Ankunft beim ersten Wort) statt mit fester Haltezeit.
//
// Umgebung: AKTE_WEB_LOGIN / AKTE_WEB_PASSWORT (eigenes Render-Konto der Redaktion, nie im Repo),
// AKTE_PLAYWRIGHT (Pfad zum Playwright-Paket, Standard: render/node_modules), FFMPEG (Standard: ffmpeg im PATH),
// AKTE_AUSGABE (Zielordner, Standard: ./ausgabe), AKTE_EINSPIELER_WURZELN (erlaubte Ordner für O-Töne, Trenner ;).
// Fortschritt als JSON-Zeilen auf stdout: {"art":"bild","format":"16x9","bild":12,"von":1130}.

"use strict"

const fs = require("fs")
const os = require("os")
const path = require("path")
const { spawn } = require("child_process")

// Einspieler-Dateien nur aus diesen Ordnern (die Pfade stehen in der Datenbank; hier wird nochmals geprüft).
const WINDOWS = process.platform === "win32"
const klein = (p) => (WINDOWS ? p.toLowerCase() : p)
const EINSPIELER_WURZELN = (process.env.AKTE_EINSPIELER_WURZELN || "")
  .split(";").filter(Boolean).map((w) => klein(path.resolve(w)))

/** Zerlegt den Ausschnitt in Einzelbilder (25 fps): das Chromium des Renderers spielt kein H.264 ab. */
function einspielerBilder(e, ziel) {
  const datei = fs.realpathSync.native(path.resolve(e.datei))
  if (!EINSPIELER_WURZELN.some((w) => klein(datei).startsWith(w + path.sep))) throw new Error(`Einspieler außerhalb der erlaubten Ordner (AKTE_EINSPIELER_WURZELN): ${e.datei}`)
  if (!/\.(mp4|mov|webm|mkv)$/i.test(datei)) throw new Error(`Einspieler ist kein Video: ${e.datei}`)
  fs.mkdirSync(ziel, { recursive: true })
  const r = require("child_process").spawnSync(process.env.FFMPEG || "ffmpeg", [
    "-v", "error", "-y", "-ss", String(e.ab), "-to", String(e.bis), "-i", datei,
    "-vf", "fps=25,scale=1600:-2:flags=lanczos", "-q:v", "2", path.join(ziel, "%05d.jpg"),
  ], { encoding: "utf-8" })
  if (r.status !== 0) throw new Error(`ffmpeg (Einspieler): ${String(r.stderr).slice(-400)}`)
  const anzahl = fs.readdirSync(ziel).filter((n) => n.endsWith(".jpg")).length
  if (!anzahl) throw new Error(`Einspieler ergab 0 Bilder (ab/bis hinter dem Dateiende?): ${e.datei}`)
  return anzahl
}

const FORMATE = { "16x9": [1920, 1080], "9x16": [1080, 1920], "1x1": [1080, 1080], oben: [1080, 960] }
const FPS = 25
// Bewegungsunschärfe: 4 Unterbilder über einen 180°-Verschluss (20 ms je Bild bei 25 fps).
const UNTERBILDER = [-7.5, -2.5, 2.5, 7.5]

function argumente(argv) {
  const a = { formate: "16x9", halte: "3000", basis: process.env.AKTE_WEB || "http://127.0.0.1:8080" }
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i]
    if (!k.startsWith("--")) continue
    const name = k.slice(2)
    if (["stichworte", "legende", "4k", "unschaerfe"].includes(name)) a[name] = true
    else a[name] = argv[++i]
  }
  return a
}

function melde(obj) {
  process.stdout.write(`${JSON.stringify(obj)}\n`)
}

/** Dateiname aus einem Titel: klein, Umlaute ausgeschrieben, nur a–z, 0–9 und Bindestrich. */
function slug(text) {
  return String(text).toLowerCase()
    .replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss")
    .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60) || "fahrt"
}

function heute() {
  const d = new Date()
  const zwei = (n) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${zwei(d.getMonth() + 1)}-${zwei(d.getDate())}`
}

function pruefe(a) {
  if (!/^[a-z0-9-]{1,80}$/.test(a.board || "")) throw new Error("--board fehlt oder ist ungültig")
  if (!/^\d{1,9}$/.test(a.fahrt || "")) throw new Error("--fahrt braucht die Fahrt-ID (Zahl)")
  const formate = String(a.formate).split(",").map((f) => f.trim()).filter(Boolean)
  for (const f of formate) if (!FORMATE[f]) throw new Error(`Unbekanntes Format ${f} (erlaubt: ${Object.keys(FORMATE).join(", ")})`)
  const halte = Number(a.halte)
  if (!Number.isFinite(halte) || halte < 1000 || halte > 8000) throw new Error("--halte zwischen 1000 und 8000 ms")
  if (a.look && !["dunkel", "papier"].includes(a.look)) throw new Error("--look dunkel|papier")
  if (!/^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(a.basis)) throw new Error("--basis nur lokal (http://127.0.0.1:<port>)")
  return { formate, halte }
}

function ffmpegStarten(ziel, unterbilder) {
  const filter = unterbilder > 1
    ? ["-vf", `tmix=frames=${unterbilder},select=not(mod(n+1\\,${unterbilder})),setpts=N/${FPS}/TB`]
    : []
  const args = [
    "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(FPS * unterbilder), "-i", "-",
    ...filter,
    "-r", String(FPS), "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p",
    "-movflags", "+faststart", "-an", ziel,
  ]
  const p = spawn(process.env.FFMPEG || "ffmpeg", args, { stdio: ["pipe", "ignore", "pipe"] })
  let fehler = ""
  p.stderr.on("data", (d) => { fehler += d })
  const fertig = new Promise((ok, nein) => {
    p.on("error", nein)
    p.on("close", (code) => (code === 0 ? ok() : nein(new Error(`ffmpeg ${code}: ${fehler.slice(-600)}`))))
  })
  return {
    async schreibe(buf) {
      if (!p.stdin.write(buf)) await new Promise((ok) => p.stdin.once("drain", ok))
    },
    async schliesse() {
      p.stdin.end()
      await fertig
    },
  }
}

async function main() {
  const a = argumente(process.argv.slice(2))
  const { formate, halte } = pruefe(a)
  const login = process.env.AKTE_WEB_LOGIN
  const passwort = process.env.AKTE_WEB_PASSWORT
  if (!login || !passwort) throw new Error("AKTE_WEB_LOGIN und AKTE_WEB_PASSWORT setzen (eigenes Render-Konto)")
  const pw = require(process.env.AKTE_PLAYWRIGHT || "playwright")

  const fahrtName = slug(a.name || a.titel || `fahrt-${a.fahrt}`)
  // Im Takt der Stimme: Satzanfänge je Station aus render/vertonen.py.
  let zeiten = null
  if (a.zeiten) {
    zeiten = JSON.parse(fs.readFileSync(a.zeiten, "utf-8"))
    if (!Array.isArray(zeiten.stationen) || !zeiten.stationen.every(Number.isFinite) || !Number.isFinite(zeiten.ende_ms)) {
      throw new Error("--zeiten braucht {stationen: [ms, …], ende_ms}")
    }
  }
  const ziel = a.ziel || path.join(process.env.AKTE_AUSGABE || path.join(process.cwd(), "ausgabe"), `${heute()}_akte-${a.board}-${fahrtName}`)
  fs.mkdirSync(path.join(ziel, "standbilder"), { recursive: true })
  const zusatz = `${a["4k"] ? "_4k" : ""}${a.unschaerfe ? "_unschaerfe" : ""}`

  const aufzuraeumen = []
  const browser = await pw.chromium.launch({
    args: ["--force-color-profile=srgb", "--hide-scrollbars", "--disable-lcd-text", "--font-render-hinting=none"],
  })
  const ergebnis = { board: a.board, fahrt: Number(a.fahrt), titel: a.titel || "", ziel, dateien: [], start: new Date().toISOString() }
  try {
    for (const format of formate) {
      const [b, h] = FORMATE[format]
      const dichte = a["4k"] ? 2 : 1
      const kontext = await browser.newContext({ viewport: { width: b, height: h }, deviceScaleFactor: dichte, reducedMotion: "no-preference" })
      if (zeiten) await kontext.addInitScript((z) => { window.__akteZeiten = z }, { stationen: zeiten.stationen, ende_ms: zeiten.ende_ms })
      const anmeldung = await kontext.request.post(`${a.basis}/api/auth/login`, { data: { login, password: passwort } })
      if (!anmeldung.ok()) throw new Error(`Anmeldung fehlgeschlagen (${anmeldung.status()})`)
      const page = await kontext.newPage()
      const fehlerSeite = []
      page.on("pageerror", (e) => fehlerSeite.push(String(e)))
      const q = new URLSearchParams({ fahrt: a.fahrt, format, halte: String(halte) })
      if (a.look) q.set("look", a.look)
      if (a.stichworte) q.set("stichworte", "1")
      if (a.legende) q.set("legende", "1")
      // Video-Schalter: Abdunkeln, Etiketten, Karten weglassen, unten frei
      if (a.dimm !== undefined) q.set("dimm", String(a.dimm))
      if (a.etiketten) q.set("etiketten", String(a.etiketten))
      if (a.ohne) q.set("ohne", String(a.ohne))
      if (a["frei-unten"]) q.set("frei_unten", String(a["frei-unten"]))
      await page.goto(`${a.basis}/akte/${a.board}/render?${q}`, { waitUntil: "networkidle", timeout: 60000 })
      await page.waitForFunction(() => !!window.__akteRender, null, { timeout: 60000 })
      const info = await page.evaluate(() => window.__akteRender.bereit())
      const bilder = Math.ceil((info.dauerMs / 1000) * FPS)
      if (bilder <= 0 || !info.stationen.length) throw new Error("Die Fahrt hat keine Stationen.")
      if (zeiten && !info.getaktet) {
        throw new Error("zeiten.json passt nicht zur Fahrt (Anzahl oder Sprechtexte geändert) — erst neu vertonen.")
      }
      // Einspieler: Einzelbilder vorbereiten und unter /__einspieler/<station>/<nr>.jpg ausliefern.
      const einspielerOrdner = fs.mkdtempSync(path.join(os.tmpdir(), "akte-einspieler-"))
      aufzuraeumen.push(einspielerOrdner)
      for (const e of info.einspieler || []) {
        const anzahl = einspielerBilder(e, path.join(einspielerOrdner, String(e.station)))
        melde({ art: "einspieler", format, station: e.station + 1, bilder: anzahl })
      }
      await kontext.route("**/__einspieler/**", (route) => {
        const m = /\/__einspieler\/(\d{1,3})\/(\d{5})\.jpg$/.exec(new URL(route.request().url()).pathname)
        const datei = m && path.join(einspielerOrdner, m[1], `${m[2]}.jpg`)
        if (datei && fs.existsSync(datei)) return route.fulfill({ path: datei, contentType: "image/jpeg" })
        // Nach dem letzten Bild steht das Standbild: das höchste vorhandene Bild ausliefern.
        if (m && fs.existsSync(path.join(einspielerOrdner, m[1]))) {
          const alle = fs.readdirSync(path.join(einspielerOrdner, m[1])).filter((n) => n.endsWith(".jpg")).sort()
          if (alle.length) return route.fulfill({ path: path.join(einspielerOrdner, m[1], alle[alle.length - 1]), contentType: "image/jpeg" })
        }
        return route.fulfill({ status: 404, body: "" })
      })
      if (info.fehlendeBilder.length) {
        melde({ art: "warnung", format, text: `${info.fehlendeBilder.length} Bild(er) nicht geladen: ${info.fehlendeBilder.slice(0, 3).join(", ")}` })
      }
      melde({ art: "format", format, bilder, dauerMs: info.dauerMs, stationen: info.stationen.length })

      const cdp = await kontext.newCDPSession(page)
      // Ohne clip.scale liefert CDP CSS-Pixel und ignoriert die Pixeldichte (4K käme als 1080p heraus).
      const foto = async () => {
        const r = await cdp.send("Page.captureScreenshot", {
          format: "png", optimizeForSpeed: true, clip: { x: 0, y: 0, width: b, height: h, scale: dichte },
        })
        return Buffer.from(r.data, "base64")
      }
      const datei = path.join(ziel, `${a.board}_${fahrtName}_${format}${zusatz}.mp4`)
      const unter = a.unschaerfe ? UNTERBILDER : [0]
      const ff = ffmpegStarten(datei, unter.length)
      const t0 = Date.now()
      for (let k = 0; k < bilder; k++) {
        for (const versatz of unter) {
          await page.evaluate((ms) => window.__akteRender.setzeZeit(ms), Math.max(0, (k * 1000) / FPS + versatz))
          await ff.schreibe(await foto())
        }
        if (k % 25 === 0 || k === bilder - 1) melde({ art: "bild", format, bild: k + 1, von: bilder, sekunden: Math.round((Date.now() - t0) / 1000) })
      }
      await ff.schliesse()
      ergebnis.dateien.push(datei)

      // Standbilder: Mitte des Haltens jeder Station, in voller Auflösung.
      for (const [i, s] of info.stationen.entries()) {
        await page.evaluate((ms) => window.__akteRender.setzeZeit(ms), s.standbild)
        const bild = path.join(ziel, "standbilder", `${a.board}_${fahrtName}_${format}${a["4k"] ? "_4k" : ""}_s${String(i + 1).padStart(2, "0")}.png`)
        fs.writeFileSync(bild, await foto())
      }
      if (fehlerSeite.length) melde({ art: "warnung", format, text: fehlerSeite.slice(0, 3).join(" | ") })
      // Der Zeitplan (Flugbeginn, Ankunft je Station) reist mit: render/mischen.py setzt die Klänge darauf.
      ergebnis.plaene = ergebnis.plaene || {}
      ergebnis.plaene[format] = {
        dauerMs: info.dauerMs,
        stationen: info.stationen.map((s) => ({ start: s.start, ankunft: s.ankunft, einspieler: s.einspieler || null })),
      }
      ergebnis.plan = ergebnis.plan || ergebnis.plaene[format]
      melde({ art: "fertig", format, datei })
      await kontext.close()
    }
  } finally {
    await browser.close()
    // Einzelbilder der O-Töne nicht in %TEMP% liegen lassen, auch wenn ein Format abbricht.
    for (const ordner of aufzuraeumen) fs.rmSync(ordner, { recursive: true, force: true })
  }
  ergebnis.ende = new Date().toISOString()
  ergebnis.einstellungen = { formate, halte, look: a.look || "board", stichworte: !!a.stichworte, legende: !!a.legende, "4k": !!a["4k"], unschaerfe: !!a.unschaerfe }
  fs.writeFileSync(path.join(ziel, `auftrag_${fahrtName}${zusatz}.json`), JSON.stringify(ergebnis, null, 2))
  melde({ art: "ende", ziel, dateien: ergebnis.dateien })
}

main().catch((e) => {
  melde({ art: "fehler", text: String(e && e.message ? e.message : e) })
  process.exit(1)
})
