"use client"

// Eigene Anfragen (Speichern, Hochladen, Unterschreiben, Regeln) melden sich bei der Wand an. Solange eine läuft,
// verwirft die Live-Aktualisierung ihre Antworten: Was man selbst tut, ist nicht „neu auf der Wand“. Danach lädt die
// Wand genau einmal nach. Ohne Wand (etwa in einem Test) läuft die Arbeit einfach so.

import { createContext, useContext } from "react"

export type EigeneAnfrage = <T>(arbeit: () => Promise<T>) => Promise<T>

const Kontext = createContext<EigeneAnfrage>((arbeit) => arbeit())

export const EigeneAnfrageAnbieter = Kontext.Provider

export function useEigeneAnfrage(): EigeneAnfrage {
  return useContext(Kontext)
}
