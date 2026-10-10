#!/usr/bin/env node
// Lokaler Render-Dienst für den Knopf „Video rendern“ im Aufnahme-Dialog der Akte.
// Hört nur auf 127.0.0.1:8178, nimmt nur Aufträge von lokalen Seiten an und startet je Auftrag
// render/render_fahrt.cjs (ohne Shell, feste Argumente). Höchstens ein Auftrag gleichzeitig.
//
//   set AKTE_WEB_LOGIN=...  set AKTE_WEB_PASSWORT=...   (Render-Konto, nie im Repo)
//   node render/render_dienst.cjs
//
// Umgebung: AKTE_DIENST_PORT (8178), AKTE_WEB (http://127.0.0.1:8080, die laufende Akte).

"use strict"

const fs = require("fs")
const http = require("http")
const path = require("path")
const { randomUUID } = require("crypto")
const { spawn } = require("child_process")

const PORT = Number(process.env.AKTE_DIENST_PORT || 8178)
const WEB = (process.env.AKTE_WEB || "http://127.0.0.1:8080").replace(/\/$/, "")
const RENDERER = path.join(__dirname, "render_fahrt.cjs")
const FORMATE = ["16x9", "9x16", "1x1", "oben"]
// Nur die Akte selbst darf Aufträge geben: exakt ihr Origin (auch in localhost-Schreibweise), kein anderer Port.
const WEB_URL = new URL(WEB)
const ERLAUBT = new Set([WEB_URL.origin, `http://localhost:${WEB_URL.port}`, `http://127.0.0.1:${WEB_URL.port}`])
const MAX_KOERPER = 4096
const MAX_AUFTRAEGE = 20

/** @type {Map<string, object>} */
const auftraege = new Map()
let laufend = null

function antworte(res, status, daten, kopf = {}) {
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...kopf })
  res.end(JSON.stringify(daten))
}

/**
 * Nur die Akte-Seite auf diesem Rechner: Host-Prüfung gegen DNS-Rebinding, Origin exakt gegen die Akte.
 * Ohne Origin (curl) nur `/status` — die CLI braucht den Dienst nicht, sie startet den Renderer selbst.
 */
function erlaubt(req, pfad) {
  const host = req.headers.host || ""
  if (!new RegExp(`^(127\\.0\\.0\\.1|localhost):${PORT}$`).test(host)) return null
  const herkunft = req.headers.origin
  if (herkunft === undefined) return pfad === "/status" ? "" : null
  return ERLAUBT.has(herkunft) ? herkunft : null
}

/** Fehlertexte ohne Zugangsdaten (falls ein Kindprozess mit DEBUG=pw:* Anfragen protokolliert). */
function geschwaerzt(text) {
  return String(text)
    .replace(/("?(password|passwort|login|token|authorization)"?\s*[:=]\s*)("[^"]*"|\S+)/gi, "$1***")
    .slice(0, 400)
}

function koerper(req) {
  return new Promise((ok, nein) => {
    let daten = ""
    req.on("data", (s) => {
      daten += s
      if (daten.length > MAX_KOERPER) { nein(new Error("zu groß")); req.destroy() }
    })
    req.on("end", () => { try { ok(JSON.parse(daten || "{}")) } catch { nein(new Error("kein JSON")) } })
  })
}

/** Prüft den Auftrag und baut die Argumentliste — nichts davon geht durch eine Shell. */
function argumenteAus(e) {
  if (!/^[a-z0-9-]{1,80}$/.test(String(e.board))) throw new Error("board ungültig")
  if (!Number.isInteger(e.fahrt) || e.fahrt <= 0) throw new Error("fahrt ungültig")
  const formate = Array.isArray(e.formate) ? e.formate.filter((f) => FORMATE.includes(f)) : []
  if (!formate.length || formate.length !== e.formate.length) throw new Error("formate ungültig")
  const halte = Number(e.halte ?? 3000)
  if (!Number.isFinite(halte) || halte < 1000 || halte > 8000) throw new Error("halte ungültig")
  if (e.look !== undefined && !["dunkel", "papier"].includes(e.look)) throw new Error("look ungültig")
  const titel = String(e.titel ?? "").slice(0, 200)
  const a = ["--board", e.board, "--fahrt", String(e.fahrt), "--titel", titel, "--formate", formate.join(","),
    "--halte", String(Math.round(halte)), "--basis", WEB]
  if (e.look) a.push("--look", e.look)
  if (e.stichworte === true) a.push("--stichworte")
  if (e.legende === true) a.push("--legende")
  if (e.vierk === true) a.push("--4k")
  if (e.unschaerfe === true) a.push("--unschaerfe")
  return a
}

function starte(e) {
  const id = randomUUID()
  const auftrag = { id, status: "laeuft", formate: {}, dateien: [], ziel: "", fehler: "", start: Date.now() }
  const p = spawn(process.execPath, [RENDERER, ...argumenteAus(e)], { stdio: ["ignore", "pipe", "pipe"], windowsHide: true })
  let rest = ""
  p.stdout.on("data", (d) => {
    rest += d
    const zeilen = rest.split("\n")
    rest = zeilen.pop()
    for (const z of zeilen) {
      let m
      try { m = JSON.parse(z) } catch { continue }
      if (m.art === "format") auftrag.formate[m.format] = { bild: 0, von: m.bilder }
      if (m.art === "bild") auftrag.formate[m.format] = { bild: m.bild, von: m.von }
      if (m.art === "fertig") auftrag.dateien.push(m.datei)
      if (m.art === "ende") auftrag.ziel = m.ziel
      if (m.art === "fehler") auftrag.fehler = geschwaerzt(m.text)
    }
  })
  p.stderr.on("data", (d) => { if (!auftrag.fehler) auftrag.fehler = geschwaerzt(d) })
  p.on("close", (code) => {
    auftrag.status = code === 0 ? "fertig" : "fehler"
    laufend = null
  })
  auftraege.set(id, auftrag)
  // Alte Aufträge vergessen, damit die Liste über lange Laufzeit nicht wächst.
  for (const alt of auftraege.keys()) {
    if (auftraege.size <= MAX_AUFTRAEGE) break
    if (alt !== id) auftraege.delete(alt)
  }
  laufend = id
  return auftrag
}

const server = http.createServer(async (req, res) => {
  const herkunft = erlaubt(req, (req.url || "").split("?")[0])
  if (herkunft === null) return antworte(res, 403, { fehler: "nur die Akte auf diesem Rechner" })
  const cors = herkunft ? { "Access-Control-Allow-Origin": herkunft, Vary: "Origin" } : {}
  if (req.method === "OPTIONS") {
    res.writeHead(204, { ...cors, "Access-Control-Allow-Methods": "GET, POST", "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "600" })
    return res.end()
  }
  const url = new URL(req.url, `http://127.0.0.1:${PORT}`)
  const teile = url.pathname.split("/").filter(Boolean)
  try {
    if (req.method === "GET" && url.pathname === "/status") {
      return antworte(res, 200, { bereit: true, laeuft: laufend }, cors)
    }
    if (req.method === "POST" && url.pathname === "/auftrag") {
      if (laufend) return antworte(res, 409, { fehler: "Es läuft schon ein Auftrag.", id: laufend }, cors)
      const a = starte(await koerper(req))
      return antworte(res, 202, a, cors)
    }
    const a = teile[0] === "auftrag" ? auftraege.get(teile[1]) : undefined
    if (!a) return antworte(res, 404, { fehler: "unbekannt" }, cors)
    if (req.method === "GET" && teile.length === 2) return antworte(res, 200, a, cors)
    if (req.method === "POST" && teile[2] === "oeffnen" && a.ziel) {
      // Nur der Ordner, den der Renderer selbst gemeldet hat.
      spawn("explorer.exe", [path.resolve(a.ziel)], { detached: true, stdio: "ignore" }).unref()
      return antworte(res, 200, { ok: true }, cors)
    }
    if (req.method === "GET" && teile[2] === "datei") {
      const datei = a.dateien[Number(teile[3])]
      if (!datei || !fs.existsSync(datei)) return antworte(res, 404, { fehler: "keine Datei" }, cors)
      res.writeHead(200, {
        ...cors, "Content-Type": "video/mp4", "Content-Length": fs.statSync(datei).size,
        "Content-Disposition": `attachment; filename="${path.basename(datei).replace(/[^\w.-]/g, "_")}"`,
      })
      return fs.createReadStream(datei).pipe(res)
    }
    return antworte(res, 404, { fehler: "unbekannt" }, cors)
  } catch (e) {
    return antworte(res, 400, { fehler: String(e.message || e) }, cors)
  }
})

if (!process.env.AKTE_WEB_LOGIN || !process.env.AKTE_WEB_PASSWORT) {
  console.error("AKTE_WEB_LOGIN und AKTE_WEB_PASSWORT setzen (Render-Konto der Redaktion).")
  process.exit(1)
}
server.listen(PORT, "127.0.0.1", () => console.log(`Akte-Render-Dienst auf http://127.0.0.1:${PORT} (Web: ${WEB})`))
