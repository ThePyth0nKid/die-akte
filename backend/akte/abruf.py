"""Sicherer Abruf fremder Links — die Akte lädt nur, was im offenen Internet liegt.

Wer eine Quelle einträgt, bestimmt die Adresse, die unser Server abruft. Ohne
Schutz könnte so ein Link auf interne Dienste zeigen (Metadaten des Hosters,
Redis, die eigene Datenbank). Deshalb:

* nur ``http``/``https`` auf Port 80/443,
* jede Adresse vor dem Verbinden auflösen und nur öffentliche IPs zulassen,
* die IP, mit der sich der Socket **tatsächlich** verbunden hat, noch einmal
  prüfen (gegen DNS-Rebinding zwischen Prüfung und Verbindung),
* Weiterleitungen einzeln und neu prüfen (höchstens fünf),
* Größe beim Lesen begrenzen, Zeitlimits setzen, keine Proxy-Variablen.
"""

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

MAX_BYTES = 50 * 1024 * 1024
MAX_WEITERLEITUNGEN = 5
ZEITLIMIT = (10, 40)
ERLAUBTE_PORTS = {80, 443}
KENNUNG = f"Mozilla/5.0 (compatible; {settings.AKTE_ABRUF_KENNUNG}; Beweissicherung)"


class AbrufFehler(Exception):
    """Der Abruf wurde verweigert oder ist gescheitert; die Nachricht ist für Menschen."""


def oeffentlich(ip: str) -> bool:
    adresse = ipaddress.ip_address(ip)
    if adresse.version == 6 and adresse.ipv4_mapped:
        adresse = adresse.ipv4_mapped
    return adresse.is_global and not adresse.is_multicast


def pruefe_url(url: str) -> None:
    teile = urlparse(url)
    if teile.scheme not in ("http", "https") or not teile.hostname:
        raise AbrufFehler(f"Nur http- und https-Links: {url[:120]}")
    port = teile.port or (443 if teile.scheme == "https" else 80)
    if port not in ERLAUBTE_PORTS:
        raise AbrufFehler(f"Port {port} ist nicht erlaubt.")
    try:
        adressen = {info[4][0] for info in socket.getaddrinfo(teile.hostname, port, type=socket.SOCK_STREAM)}
    except socket.gaierror:
        raise AbrufFehler(f"Adresse nicht auflösbar: {teile.hostname}") from None
    if not adressen or not all(oeffentlich(ip) for ip in adressen):
        raise AbrufFehler(f"{teile.hostname} zeigt nicht ins offene Internet.")


class _PruefeGegenstelle:
    """Prüft nach dem Verbinden, mit welcher IP der Socket wirklich spricht."""

    def _new_conn(self):
        sock = super()._new_conn()
        ip = sock.getpeername()[0]
        if not oeffentlich(ip):
            sock.close()
            raise AbrufFehler(f"Verbindung zu {ip} verweigert (nicht öffentlich).")
        return sock


class _HTTPVerbindung(_PruefeGegenstelle, HTTPConnection):
    pass


class _HTTPSVerbindung(_PruefeGegenstelle, HTTPSConnection):
    pass


class _HTTPPool(HTTPConnectionPool):
    ConnectionCls = _HTTPVerbindung


class _HTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _HTTPSVerbindung


class _PruefAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {"http": _HTTPPool, "https": _HTTPSPool}


def _sitzung() -> requests.Session:
    s = requests.Session()
    s.trust_env = False  # keine Proxy-Variablen aus der Umgebung
    s.mount("http://", _PruefAdapter())
    s.mount("https://", _PruefAdapter())
    s.headers.update({"User-Agent": KENNUNG, "Accept-Language": "de,en;q=0.8"})
    return s


@dataclass
class Abruf:
    url: str  # nach allen Weiterleitungen
    status: int
    mime_kopf: str
    daten: bytes


def abrufen(url: str, max_bytes: int = MAX_BYTES) -> Abruf:
    sitzung = _sitzung()
    ziel = url
    for _ in range(MAX_WEITERLEITUNGEN + 1):
        pruefe_url(ziel)
        try:
            antwort = sitzung.get(ziel, stream=True, allow_redirects=False, timeout=ZEITLIMIT)
        except AbrufFehler:
            raise
        except requests.RequestException as fehler:
            raise AbrufFehler(f"Abruf gescheitert: {type(fehler).__name__}") from None
        if antwort.is_redirect:
            ort = antwort.headers.get("Location", "")
            antwort.close()
            if not ort:
                raise AbrufFehler("Weiterleitung ohne Ziel.")
            ziel = urljoin(ziel, ort)
            continue
        if antwort.status_code >= 400:
            antwort.close()
            raise AbrufFehler(f"Die Seite antwortet mit {antwort.status_code}.")
        teile, groesse = [], 0
        for stueck in antwort.iter_content(64 * 1024):
            groesse += len(stueck)
            if groesse > max_bytes:
                antwort.close()
                raise AbrufFehler(f"Größer als {max_bytes // (1024 * 1024)} MB.")
            teile.append(stueck)
        return Abruf(ziel, antwort.status_code, antwort.headers.get("Content-Type", ""), b"".join(teile))
    raise AbrufFehler("Zu viele Weiterleitungen.")


# ─── Was ist das für eine Datei? ─────────────────────────────────────────────

ARTEN = {
    "pdf": ("application/pdf", "pdf"),
    "png": ("image/png", "png"),
    "jpeg": ("image/jpeg", "jpg"),
    "gif": ("image/gif", "gif"),
    "webp": ("image/webp", "webp"),
    "html": ("text/html", "html"),
    "sonstiges": ("application/octet-stream", "bin"),
}


def erkenne(daten: bytes) -> str:
    """Art nach den ersten Bytes, nie nach dem, was der Server oder der Dateiname behauptet."""
    if daten.startswith(b"%PDF-"):
        return "pdf"
    if daten.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if daten.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if daten.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if daten[:4] == b"RIFF" and daten[8:12] == b"WEBP":
        return "webp"
    kopf = daten[:4096].lstrip().lower()
    if kopf.startswith(b"<!doctype html") or b"<html" in kopf:
        return "html"
    return "sonstiges"


BILDER = {"png", "jpeg", "gif", "webp"}
