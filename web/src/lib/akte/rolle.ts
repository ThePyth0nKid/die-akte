// Darf das angemeldete Konto Wände anlegen, obwohl die Akte noch keine hat? Die Board-Liste verrät das nur über
// „darf_bearbeiten“ an einer Wand; eine frische Akte hat keine. Dann fragt die Übersicht nach den Einstellungen, die
// nur die Redaktion lesen darf (Durchlauf 3: das erste Konto sah „Hier ist noch nichts freigeschaltet. Anmelden“).

export async function istRedaktionOhneWand(
  angemeldet: () => Promise<boolean>,
  einstellungen: () => Promise<unknown>,
): Promise<boolean> {
  try {
    // Ohne Sitzung gar nicht erst fragen: Besucher bekämen sonst eine abgewiesene Anfrage samt Erneuerungsversuch.
    if (!(await angemeldet())) return false
    await einstellungen()
    return true
  } catch {
    return false
  }
}

/** Gibt es eine Sitzung? Die Cookies sind httpOnly; die Antwort kommt von /api/auth/sitzung. */
export async function sitzungLaeuft(): Promise<boolean> {
  // Mit Zeitgrenze: Sonst bliebe die Übersicht bei einer hängenden Anfrage für immer bei „Lädt …“.
  const r = await fetch("/api/auth/sitzung", { credentials: "include", cache: "no-store", signal: AbortSignal.timeout(5000) })
  if (!r.ok) return false
  const d = (await r.json()) as { angemeldet?: boolean }
  return Boolean(d.angemeldet)
}
