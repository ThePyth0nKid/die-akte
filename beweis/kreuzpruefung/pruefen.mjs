// SPDX-License-Identifier: MIT
// Prüft einen Trace der Akte unabhängig mit dem WASM-Prüfer von Atlas (Rust, Apache-2.0).
//
//   node beweis/kreuzpruefung/pruefen.mjs <trace.json> <buendel.json>
//
// Ausgabe: das Ergebnis des Prüfers als JSON ({valid, evidence, errors, verifier_version}). Exit 0 = gültig.
// Die Dateien gehen als roher Text an den Prüfer (große Zahlen bleiben genau).

import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import { dirname, join } from "node:path"

const require = createRequire(import.meta.url)
const paket = dirname(require.resolve("@atlas-trust/verify-wasm/package.json"))
const { initSync, verify_trace_json, verifier_version } = await import(join(paket, "atlas_verify_wasm.js")
  .replace(/\\/g, "/").replace(/^([A-Za-z]):/, "file:///$1:"))

const [traceDatei, buendelDatei] = process.argv.slice(2)
if (!traceDatei || !buendelDatei) {
  console.error("Aufruf: node pruefen.mjs <trace.json> <buendel.json>")
  process.exit(2)
}
initSync({ module: readFileSync(join(paket, "atlas_verify_wasm_bg.wasm")) })
const ergebnis = verify_trace_json(readFileSync(traceDatei, "utf-8"), readFileSync(buendelDatei, "utf-8"))
const ausgabe = typeof ergebnis === "string" ? JSON.parse(ergebnis) : ergebnis
console.log(JSON.stringify({ ...ausgabe, verifier_version: verifier_version() }))
process.exit(ausgabe.valid ? 0 : 1)
