/** Ziel nach dem Login: nur interne Pfade, kein offener Redirect auf fremde Seiten. */
export function sicheresZiel(ziel: string | null): string {
  if (!ziel || !ziel.startsWith("/") || ziel.startsWith("//") || ziel.startsWith("/\\")) return "/akte"
  return ziel
}
