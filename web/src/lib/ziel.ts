/** Ziel nach dem Login: nur interne Pfade, kein offener Redirect auf fremde Seiten.
 *
 * Browser entfernen Tab und Zeilenumbruch aus Adressen und lesen „\“ wie „/“: aus „/\t/boese.example“ würde
 * „//boese.example“. Darum fliegen Steuerzeichen und Backslashes vorab raus, und zum Schluss muss die Adresse, gegen
 * eine Platzhalter-Herkunft aufgelöst, bei dieser Herkunft bleiben.
 */
const STANDARD = "/akte"
const PLATZHALTER = "http://akte.invalid"

export function sicheresZiel(ziel: string | null): string {
  if (!ziel || ziel.length > 2000) return STANDARD
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f\\]/.test(ziel)) return STANDARD
  if (!ziel.startsWith("/") || ziel.startsWith("//")) return STANDARD
  try {
    const url = new URL(ziel, PLATZHALTER)
    if (url.origin !== PLATZHALTER) return STANDARD
    const ergebnis = url.pathname + url.search + url.hash
    // Punktsegmente lösen sich auf: aus „/.//x“ oder „/a/..//x“ wird „//x“, und das wäre wieder eine fremde Seite.
    return ergebnis.startsWith("//") ? STANDARD : ergebnis
  } catch {
    return STANDARD
  }
}
