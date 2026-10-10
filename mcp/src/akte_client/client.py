# SPDX-License-Identifier: MIT
"""HTTP-Client für die API einer Akte (``/api/v1/akte/``).

Ohne Token liest der Client nur, was Besucher ohne Konto sehen dürfen (öffentliche Boards, wenn die Instanz das
eingeschaltet hat). Mit Token (``manage.py akte_token <konto>``) arbeitet er als Werkzeug der Redaktion: Er legt
Entwürfe an und ändert Entwürfe; freigeben kann er nicht (das bleibt dem Menschen in der Oberfläche).
"""

from __future__ import annotations

from typing import Any

import requests

ZEITLIMIT = 60


class AkteFehler(Exception):
    """Antwort mit Status ≥ 400. ``daten`` ist die JSON-Antwort oder der Anfang des Textes."""

    def __init__(self, status: int, daten: Any, methode: str = "", pfad: str = ""):
        self.status = status
        self.daten = daten
        super().__init__(f"Fehler {status} bei {methode} {pfad}: {daten}")


class Akte:
    def __init__(self, basis: str, token: str | None = None, *, session: requests.Session | None = None,
                 kennung: str = "akte-client/0.1"):
        if not basis:
            raise ValueError("Adresse der Akte fehlt (z. B. http://localhost:8080).")
        self.wurzel = basis.rstrip("/")
        self.basis = f"{self.wurzel}/api/v1/akte"
        self.s = session or requests.Session()
        self.s.headers["User-Agent"] = kennung
        self.mit_token = bool(token)
        if token:
            self.s.headers["Authorization"] = f"Token {token}"

    # ─── Grundlagen ────────────────────────────────────────────────────────
    def anfrage(self, methode: str, pfad: str, **kw) -> Any:
        r = self.s.request(methode, f"{self.basis}{pfad}", timeout=ZEITLIMIT, **kw)
        if r.status_code >= 400:
            try:
                daten = r.json()
            except ValueError:
                daten = r.text[:500]
            raise AkteFehler(r.status_code, daten, methode, pfad)
        if r.status_code == 204 or not r.content:
            return None
        return r.json() if "json" in r.headers.get("Content-Type", "") else r.content

    def get(self, pfad: str, **kw) -> Any:
        return self.anfrage("GET", pfad, **kw)

    def post(self, pfad: str, daten: Any = None, **kw) -> Any:
        return self.anfrage("POST", pfad, json=daten, **kw)

    def patch(self, pfad: str, daten: Any = None, **kw) -> Any:
        return self.anfrage("PATCH", pfad, json=daten, **kw)

    def delete(self, pfad: str) -> Any:
        return self.anfrage("DELETE", pfad)

    # ─── Lesen ─────────────────────────────────────────────────────────────
    def boards(self) -> list[dict]:
        return self.get("/boards/")

    def wand(self, slug: str) -> dict:
        return self.get(f"/boards/{slug}/")

    def entitaeten(self, q: str = "", typ: str = "") -> list[dict]:
        params = {k: v for k, v in (("q", q), ("typ", typ)) if v}
        return self.get("/entitaeten/", params=params)

    def entitaet_finden(self, name: str) -> dict | None:
        for e in self.entitaeten(q=name):
            if e["name"].lower() == name.lower() or e["slug"] == name.lower():
                return e
        return None

    def pruefung(self, slug: str) -> dict:
        return self.get(f"/boards/{slug}/pruefung/")

    def weg(self, von: int, nach: int, nur_belegt: bool = True, tiefe: int = 4) -> dict:
        return self.get("/weg/", params={"von": von, "nach": nach, "tiefe": min(tiefe, 6),
                                         "nur_belegt": "1" if nur_belegt else ""})

    def sicherungen(self, quelle_id: int) -> list[dict]:
        return self.get(f"/quellen/{quelle_id}/sicherungen/")

    # ─── Schreiben (Entwürfe) ──────────────────────────────────────────────
    def entitaet(self, name: str, typ: str | None = None, kurz: str = "", oeffentlich: bool = False,
                 notiz: str = "") -> tuple[dict, bool]:
        """Karte holen oder als Entwurf anlegen. Gibt (karte, neu) zurück."""
        e = self.entitaet_finden(name)
        if e:
            return e, False
        if not typ:
            raise ValueError(f"„{name}“ gibt es nicht. Zum Anlegen den Typ angeben.")
        return self.post("/entitaeten/", {"name": name, "typ": typ, "kurzbeschreibung": kurz,
                                          "oeffentliche_person": oeffentlich, "notiz_md": notiz}), True

    def quelle(self, titel: str, url: str = "", herausgeber: str = "", guete: str = "sekundaer",
               abgerufen: str | None = None, veroeffentlicht: str | None = None) -> tuple[dict, bool]:
        """Quelle holen (gleiche URL) oder anlegen; das Anlegen stößt die Beweissicherung an."""
        if url:
            for q in self.get("/quellen/", params={"q": url}):
                if q["url"] == url:
                    return q, False
        return self.post("/quellen/", {"titel": titel, "url": url, "herausgeber": herausgeber, "guete": guete,
                                       "abgerufen_am": abgerufen, "veroeffentlicht_am": veroeffentlicht}), True

    def auf_board(self, slug: str, entitaet_id: int, x: float | None = None, y: float | None = None,
                  wand: dict | None = None) -> dict:
        """Karte auf die Wand legen. ``wand`` spart den Abruf, wenn viele Karten auf einmal kommen."""
        wand = wand or self.wand(slug)
        for k in wand["karten"]:
            if k["entitaet"] == entitaet_id:
                return k
        if x is None:
            # Rechts neben die Wand legen; „aufraeumen“ ordnet danach ein.
            x = max((k["x"] for k in wand["karten"]), default=0) + 400
            y = min((k["y"] for k in wand["karten"]), default=0)
        karte = self.post(f"/boards/{slug}/karten/", {"entitaet": entitaet_id, "x": x, "y": y})
        wand["karten"].append(karte)
        return karte

    def mappe_legen(self, eltern: str, ziel: str, x: float | None = None, y: float | None = None,
                    farbe: str = "") -> tuple[dict, bool]:
        """Board ``ziel`` als Aktenmappe auf ``eltern``; liegt sie schon da, bleibt sie."""
        wand = self.wand(eltern)
        for m in wand.get("mappen", []):
            if m["ziel"] == ziel:
                return m, False
        if x is None:
            x = max([k["x"] for k in wand["karten"]] + [m["x"] for m in wand.get("mappen", [])], default=0) + 700
            y = min([k["y"] for k in wand["karten"]] + [m["y"] for m in wand.get("mappen", [])], default=0)
        return self.post(f"/boards/{eltern}/mappen/", {"ziel": ziel, "x": x, "y": y, "farbe": farbe}), True
