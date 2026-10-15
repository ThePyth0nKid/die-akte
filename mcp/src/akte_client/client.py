# SPDX-License-Identifier: MIT
"""HTTP-Client für die API einer Akte (``/api/v1/akte/``).

Ohne Token liest der Client nur, was Besucher ohne Konto sehen dürfen (öffentliche Boards, wenn die Instanz das
eingeschaltet hat). Mit Token (``manage.py akte_token <konto>``) arbeitet er als Werkzeug der Redaktion: Er legt
Entwürfe an und ändert Entwürfe; freigeben kann er nicht (das bleibt dem Menschen in der Oberfläche).
"""

from __future__ import annotations

import ipaddress
import sys
from typing import Any
from urllib.parse import urlsplit

import requests

ZEITLIMIT = 60
#: Die Zitatprüfung antwortet auf dem Server nach höchstens 30 s; der Client wartet etwas länger, nicht 60 s.
ZEITLIMIT_PRUEFEN = 45


class AkteFehler(Exception):
    """Antwort mit Status ≥ 400. ``daten`` ist die JSON-Antwort oder der Anfang des Textes."""

    def __init__(self, status: int, daten: Any, methode: str = "", pfad: str = "", text: str | None = None):
        self.status = status
        self.daten = daten
        super().__init__(text or f"Fehler {status} bei {methode} {pfad}: {daten}")


class AkteNichtErreichbar(AkteFehler):
    """Keine (brauchbare) Antwort von der Akte: läuft nicht, falsche Adresse, Zeitüberschreitung. ``status`` ist 0."""

    def __init__(self, text: str):
        super().__init__(0, text, text=text)


def _sicherer_weg(basis: str) -> bool:
    """https, oder eine Adresse auf diesem Rechner (dann verlässt der Token den Rechner nicht)."""
    teile = urlsplit(basis)
    if teile.scheme == "https":
        return True
    host = (teile.hostname or "").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


_gewarnt: set[str] = set()


def _warnen_unsicher(basis: str) -> None:
    """E5: Ein Token über unverschlüsseltes HTTP zu einem anderen Rechner kann im Netz mitgelesen werden. Nur warnen
    (auf stderr, stdout gehört beim MCP-Server dem Protokoll), nicht abbrechen: Installationen im eigenen LAN laufen
    weiter."""
    if basis in _gewarnt:
        return
    _gewarnt.add(basis)
    print(f"Warnung: AKTE_TOKEN geht unverschlüsselt an {basis}. Im Netz kann ihn jemand mitlesen. Besser https "
          "oder die Akte auf diesem Rechner (localhost).", file=sys.stderr)


class Akte:
    def __init__(self, basis: str, token: str | None = None, *, session: requests.Session | None = None,
                 kennung: str = "akte-client/0.2"):
        if not basis:
            raise ValueError("Adresse der Akte fehlt (z. B. http://localhost:8080).")
        self.wurzel = basis.rstrip("/")
        self.basis = f"{self.wurzel}/api/v1/akte"
        self.s = session or requests.Session()
        self.s.headers["User-Agent"] = kennung
        self.mit_token = bool(token)
        #: Token über unverschlüsseltes HTTP zu einem anderen Rechner (E5); der MCP-Server sagt es auch dem Modell.
        self.unsicher = bool(token) and not _sicherer_weg(self.wurzel)
        if token:
            self.s.headers["Authorization"] = f"Token {token}"
            if self.unsicher:
                _warnen_unsicher(self.wurzel)

    # ─── Grundlagen ────────────────────────────────────────────────────────
    def anfrage(self, methode: str, pfad: str, *, zeitlimit: float = ZEITLIMIT, **kw) -> Any:
        try:
            r = self.s.request(methode, f"{self.basis}{pfad}", timeout=zeitlimit, **kw)
        except requests.ConnectionError:  # auch: Verbindungsaufbau dauert zu lange (ConnectTimeout)
            raise AkteNichtErreichbar(f"Die Akte ist nicht erreichbar ({self.wurzel}). Läuft sie? "
                                      "Start: START-AKTE") from None
        except requests.Timeout:
            raise AkteNichtErreichbar(f"Die Akte ({self.wurzel}) hat nicht innerhalb von {zeitlimit:.0f} s "
                                      "geantwortet. Kurz warten und noch einmal versuchen.") from None
        except requests.RequestException as fehler:  # Auffangnetz: ungültige Adresse, abgebrochene Antwort …
            raise AkteNichtErreichbar(f"Die Verbindung zur Akte ({self.wurzel}) ist gescheitert "
                                      f"({type(fehler).__name__}). Stimmt AKTE_BASIS?") from None
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

    def zitat_pruefen(self, beleg_id: int) -> dict:
        """Steht das Zitat des Belegs in seiner Quelle? Synchron, höchstens 30 s auf dem Server."""
        return self.anfrage("POST", f"/belege/{int(beleg_id)}/pruefen/", zeitlimit=ZEITLIMIT_PRUEFEN)

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
        """Quelle holen (gleiche URL) oder anlegen; das Anlegen stößt die Beweissicherung im Hintergrund an (die
        Antwort wartet nicht darauf)."""
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
