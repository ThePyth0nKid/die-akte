"""Sicherer Abruf fremder Links — die Akte lädt nur, was im offenen Internet liegt.

Wer eine Quelle einträgt, bestimmt die Adresse, die unser Server abruft. Ohne
Schutz könnte so ein Link auf interne Dienste zeigen (Metadaten des Hosters,
Redis, die eigene Datenbank). Deshalb:

* nur ``http``/``https`` auf Port 80/443,
* jede Adresse vor dem Verbinden auflösen (mit Frist) und nur öffentliche IPs zulassen,
* genau mit der geprüften IP verbinden: keine zweite Namensauflösung, kein Durchprobieren weiterer Adressen,
* die IP, mit der sich der Socket **tatsächlich** verbunden hat, noch einmal prüfen,
* Weiterleitungen einzeln und neu prüfen (höchstens fünf),
* eine harte Gesamtfrist für Kopf und Inhalt: Läuft sie ab, schließt ein Wächter die Sockets (auch ein Server, der
  Byte für Byte tröpfelt, hält niemanden auf). Das gilt unter Linux, also in Docker. Unter Windows (Entwicklung ohne
  Docker) weckt ``shutdown`` ein blockiertes Lesen nicht; dort endet es erst an der Lesezeitgrenze (höchstens die
  Restfrist beim Start der Anfrage, also bis zu 40 s nach der Frist),
* Größe beim Lesen begrenzen, keine Proxy-Variablen.
"""

import contextvars
import ipaddress
import re
import socket
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import ConnectTimeoutError, NewConnectionError, ReadTimeoutError
from urllib3.util import connection as _u3_verbindung

MAX_BYTES = 50 * 1024 * 1024
MAX_WEITERLEITUNGEN = 5
ZEITLIMIT = (10, 40)
ERLAUBTE_PORTS = {80, 443}
KENNUNG = f"Mozilla/5.0 (compatible; {settings.AKTE_ABRUF_KENNUNG}; Beweissicherung)"
#: Gesamtfrist eines Abrufs ohne eigene Angabe (Beweissicherung im Hintergrund).
FRIST_STANDARD = 120.0
#: Höchstens so viele Namensauflösungen gleichzeitig. Eine hängende Auflösung hält ihren Platz, bis sie endet; ist
#: alles belegt, scheitert der nächste Abruf sofort, statt sich anzustellen (kein Verklemmen).
DNS_PLAETZE = 16
_dns_plaetze = threading.BoundedSemaphore(DNS_PLAETZE)

ZEIT_UM = "Zeitlimit überschritten: Die Seite antwortet zu langsam."
UNGUELTIG = "Ungültige Adresse."
_NAMENSZEICHEN = re.compile(r"[A-Za-z0-9.:\[\]-]{1,120}")


def _name(host: str | None) -> str:
    """Ein Rechnername für Meldungen. Meldungen gehen bis zum Agenten; ein „Name“ aus einer fremden Weiterleitung
    könnte Text tragen, der wie eine Anweisung aussieht. Gezeigt wird er deshalb nur aus Namenszeichen (Umlaut-Namen
    als Punycode), sonst „(ungewöhnlicher Name)“."""
    try:
        name = str(host or "").encode("idna").decode("ascii")
    except UnicodeError:
        name = ""
    return name if _NAMENSZEICHEN.fullmatch(name) else "(ungewöhnlicher Name)"


class AbrufFehler(Exception):
    """Der Abruf wurde verweigert oder ist gescheitert; die Nachricht ist für Menschen."""


def oeffentlich(ip: str) -> bool:
    adresse = ipaddress.ip_address(ip)
    if adresse.version == 6 and adresse.ipv4_mapped:
        adresse = adresse.ipv4_mapped
    return adresse.is_global and not adresse.is_multicast


def _frage(host: str, port: int) -> list[str]:
    """Adressen in der Reihenfolge des Systems, ohne Doppelte."""
    return list(dict.fromkeys(info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))


def _aufloesen(host: str, port: int, frist: float | None) -> list[str]:
    """``socket.getaddrinfo`` kennt keine Zeitgrenze: mit Frist in einem eigenen Thread, der nach Ablauf aufgegeben
    wird (er endet von selbst, sobald das System antwortet) und bis dahin einen von ``DNS_PLAETZE`` Plätzen hält."""
    if frist is None:
        return _frage(host, port)
    rest = frist - time.monotonic()
    if rest <= 0:
        raise AbrufFehler(ZEIT_UM)
    if not _dns_plaetze.acquire(blocking=False):
        raise AbrufFehler("Gerade hängen zu viele Namensauflösungen. Bitte später erneut versuchen.")
    ergebnis: dict = {}
    fertig = threading.Event()

    def frage():
        try:
            ergebnis["adressen"] = _frage(host, port)
        except BaseException as fehler:  # noqa: BLE001 — wird im wartenden Thread wieder geworfen
            ergebnis["fehler"] = fehler
        finally:
            _dns_plaetze.release()
            fertig.set()

    threading.Thread(target=frage, name="akte-dns", daemon=True).start()
    if not fertig.wait(rest):
        raise AbrufFehler(f"Adresse nicht rechtzeitig auflösbar: {_name(host)}")
    if "fehler" in ergebnis:
        raise ergebnis["fehler"]
    return ergebnis["adressen"]


def pruefe_url(url: str, frist: float | None = None) -> str:
    """Darf diese Adresse abgerufen werden? Gibt die geprüfte IP zurück, mit der verbunden wird. Wirft
    ``AbrufFehler`` (auch bei kaputten Adressen, nie ValueError)."""
    try:
        teile = urlparse(url)
        hostname = teile.hostname
        port = teile.port or (443 if teile.scheme == "https" else 80)
    except ValueError:  # „http://[::1“, Port außerhalb 0–65535 …
        raise AbrufFehler(UNGUELTIG) from None
    if teile.scheme not in ("http", "https") or not hostname:
        # Ohne die Adresse selbst: Sie kann aus einer fremden Weiterleitung stammen und geht bis zum Agenten.
        art = f" (diese beginnt mit „{teile.scheme[:20]}:“)" if teile.scheme and teile.scheme not in ("http", "https") else ""
        raise AbrufFehler(f"Nur http- und https-Links{art}.")
    if port not in ERLAUBTE_PORTS:
        raise AbrufFehler(f"Port {port} ist nicht erlaubt.")
    try:
        adressen = _aufloesen(hostname, port, frist)
    except (OSError, UnicodeError, ValueError):  # gaierror/herror sind OSError; UnicodeError: ungültiger IDNA-Name
        raise AbrufFehler(f"Adresse nicht auflösbar: {_name(hostname)}") from None
    if not adressen or not all(oeffentlich(ip) for ip in adressen):
        raise AbrufFehler(f"{_name(hostname)} zeigt nicht ins offene Internet.")
    # IPv4 zuerst: Im Docker-Netz fehlt meist eine IPv6-Route. Alle Adressen sind oben geprüft, gewählt wird nur eine.
    return next((ip for ip in adressen if ipaddress.ip_address(ip).version == 4), adressen[0])


def _anfrage_url(url: str) -> str:
    """Die Adresse so, wie ``requests`` sie abruft: Umlaut-Domains als Punycode (``müller.de`` → ``xn--mller-kva.de``).
    Nur so passt der Schlüssel der geprüften IP zum Host, den urllib3 beim Verbinden nennt. Lässt sich die Adresse
    nicht aufbereiten, bleibt sie, wie sie ist; ``pruefe_url`` lehnt sie dann mit verständlicher Meldung ab."""
    try:
        return requests.Request("GET", url).prepare().url or url
    except (requests.RequestException, ValueError, UnicodeError):
        return url


def _host(wert: str) -> str:
    return str(wert or "").strip("[]").rstrip(".").lower()


@dataclass
class _Lauf:
    """Ein Abruf: geprüfte IP je (Host, Port), je offener Verbindung eine Kopie ihres Sockets, ob die Frist abgelaufen
    ist.

    Die Kopie (``socket.dup``) hat eine eigene Nummer, die nur dieser Lauf schließt, zeigt aber auf dieselbe Verbindung.
    So trifft der Wächter immer die richtige Verbindung, auch mitten im TLS-Handschlag (dort hat der rohe Socket seine
    Nummer schon an den TLS-Socket abgegeben), und nie eine fremde, deren Nummer zufällig frei geworden ist."""

    feste_ip: dict = field(default_factory=dict)
    verbindungen: list = field(default_factory=list)
    sperre: threading.Lock = field(default_factory=threading.Lock)
    abgelaufen: bool = False
    beendet: bool = False

    def abbrechen(self) -> None:
        """Vom Wächter bei Ablauf der Frist: jede Verbindung dieses Abrufs abschalten (shutdown), damit ein blockiertes
        Lesen sofort endet."""
        with self.sperre:
            if self.beendet:
                return
            self.abgelaufen = True
            for kopie in self.verbindungen:
                try:
                    kopie.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass  # schon zu

    def ende(self) -> None:
        """Ab hier fasst der Wächter nichts mehr an; die Kopien werden geschlossen (die Verbindung selbst schließt
        ``requests``)."""
        with self.sperre:
            self.beendet = True
            kopien, self.verbindungen = self.verbindungen, []
        for kopie in kopien:
            kopie.close()


_lauf: contextvars.ContextVar[_Lauf | None] = contextvars.ContextVar("akte_abruf_lauf", default=None)


class _FesteAdresse:
    """Verbindet genau mit der IP, die ``pruefe_url`` für diesen Host geprüft hat (keine zweite Auflösung, kein
    Durchprobieren), prüft die Gegenstelle noch einmal und meldet den Socket beim Wächter an."""

    def _new_conn(self):
        lauf = _lauf.get()
        ip = lauf.feste_ip.get((_host(self.host), self.port)) if lauf is not None else None
        if ip is None:
            raise AbrufFehler("Verbindung ohne geprüfte Adresse verweigert.")
        try:
            sock = _u3_verbindung.create_connection((ip, self.port), self.timeout, source_address=self.source_address,
                                                    socket_options=self.socket_options)
        except socket.timeout as fehler:
            raise ConnectTimeoutError(self, f"Verbindung zu {self.host} nicht rechtzeitig aufgebaut.") from fehler
        except OSError as fehler:
            raise NewConnectionError(self, f"Verbindung gescheitert: {fehler}") from fehler
        gegenstelle = sock.getpeername()[0]
        if not oeffentlich(gegenstelle):
            sock.close()
            raise AbrufFehler(f"Verbindung zu {gegenstelle} verweigert (nicht öffentlich).")
        with lauf.sperre:
            if lauf.abgelaufen or lauf.beendet:
                sock.close()
                raise AbrufFehler(ZEIT_UM)
            try:
                lauf.verbindungen.append(sock.dup())
            except OSError as fehler:
                sock.close()
                raise NewConnectionError(self, f"Verbindung gescheitert: {fehler}") from fehler
        return sock


_PruefeGegenstelle = _FesteAdresse  # alter Name


class _HTTPVerbindung(_FesteAdresse, HTTPConnection):
    pass


class _HTTPSVerbindung(_FesteAdresse, HTTPSConnection):
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


def _zeitlimit(frist: float | None) -> tuple[float, float]:
    if frist is None:
        return ZEITLIMIT
    rest = frist - time.monotonic()
    if rest <= 0:
        raise AbrufFehler(ZEIT_UM)
    return (min(ZEITLIMIT[0], rest), min(ZEITLIMIT[1], rest))


def _zeitueberschreitung(fehler: BaseException) -> bool:
    """Lese- oder Verbindungszeitgrenze abgelaufen (requests, urllib3 oder der Socket selbst)?"""
    return isinstance(fehler, (requests.Timeout, ReadTimeoutError, ConnectTimeoutError, TimeoutError))


def _stuecke(antwort, frist: float | None):
    """Der Inhalt in Stücken. Mit ``frist`` liest jeder Schritt nur, was gerade da ist (``read1``), und die Frist
    gilt für den ganzen Abruf: ein Server, der Byte für Byte tröpfelt, hält die Prüfung nicht auf."""
    if frist is None or not hasattr(antwort.raw, "read1"):
        yield from antwort.iter_content(64 * 1024)
        return
    lauf = _lauf.get()
    while True:
        if time.monotonic() > frist:
            raise AbrufFehler(ZEIT_UM)
        try:
            stueck = antwort.raw.read1(64 * 1024, decode_content=True)
        except Exception as fehler:  # noqa: BLE001 — urllib3/Socket: Zeitüberschreitung, Abbruch, Dekodierfehler
            # Wächter und Lesezeitgrenze (auf die Restfrist gesetzt) können eine Spur vor der Uhr auslösen (Zeitgeber
            # unter Windows in Millisekunden). Eine Zeitüberschreitung beim Lesen heißt immer: zu langsam.
            if (lauf is not None and lauf.abgelaufen) or time.monotonic() > frist or _zeitueberschreitung(fehler):
                raise AbrufFehler(ZEIT_UM) from None
            raise AbrufFehler(f"Abruf gescheitert: {type(fehler).__name__}") from None
        if not stueck:
            # Unter Linux beendet der Wächter (shutdown) ein blockiertes Lesen mit einem sauberen Ende. Ohne Länge im
            # Kopf sähe die halbe Seite dann vollständig aus und würde als Original gesichert.
            if (lauf is not None and lauf.abgelaufen) or time.monotonic() > frist:
                raise AbrufFehler(ZEIT_UM)
            return
        yield stueck


def abrufen(url: str, max_bytes: int = MAX_BYTES, frist: float | None = None) -> Abruf:
    """Adresse abrufen, mit allen Prüfungen aus der Moduldoku.

    ``frist``: Zeitpunkt (``time.monotonic()``), bis zu dem alles fertig sein muss (Zitatprüfung: höchstens 20 s);
    ohne Angabe ``FRIST_STANDARD``. Sie gilt hart: Der Wächter schließt bei Ablauf die Sockets dieses Abrufs."""
    frist = time.monotonic() + FRIST_STANDARD if frist is None else frist
    lauf = _Lauf()
    marke = _lauf.set(lauf)
    waechter = threading.Timer(max(0.0, frist - time.monotonic()), lauf.abbrechen)
    waechter.daemon = True
    waechter.start()
    sitzung = _sitzung()
    try:
        return _abrufen(sitzung, lauf, url, max_bytes, frist)
    finally:
        lauf.ende()  # erst ab hier dürfen Sockets wieder geschlossen werden; der Wächter fasst nichts mehr an
        waechter.cancel()
        sitzung.close()
        _lauf.reset(marke)


def _abrufen(sitzung, lauf: _Lauf, url: str, max_bytes: int, frist: float) -> Abruf:
    ziel = url
    for _ in range(MAX_WEITERLEITUNGEN + 1):
        geprueft = _anfrage_url(ziel)  # derselbe Host, den urllib3 beim Verbinden nennt (Punycode)
        ip = pruefe_url(geprueft, frist)  # zuerst: lehnt auch Adressen ab, an denen urlparse scheitert
        teile_url = urlparse(geprueft)
        lauf.feste_ip[(_host(teile_url.hostname), teile_url.port or (443 if teile_url.scheme == "https" else 80))] = ip
        try:
            antwort = sitzung.get(ziel, stream=True, allow_redirects=False, timeout=_zeitlimit(frist))
        except AbrufFehler:
            raise
        except requests.RequestException as fehler:
            if lauf.abgelaufen or time.monotonic() > frist or _zeitueberschreitung(fehler):
                raise AbrufFehler(ZEIT_UM) from None
            raise AbrufFehler(f"Abruf gescheitert: {type(fehler).__name__}") from None
        except ValueError:  # requests liest „Location“ auch ohne allow_redirects schon mit (Location: http://[::1)
            raise AbrufFehler(UNGUELTIG) from None
        if antwort.is_redirect:
            ort = antwort.headers.get("Location", "")
            antwort.close()
            if not ort:
                raise AbrufFehler("Weiterleitung ohne Ziel.")
            try:
                ziel = urljoin(ziel, ort)
            except ValueError:  # Location: http://[::1 …
                raise AbrufFehler(f"Weiterleitung: {UNGUELTIG}") from None
            continue
        if antwort.status_code >= 400:
            antwort.close()
            raise AbrufFehler(f"Die Seite antwortet mit {antwort.status_code}.")
        teile, groesse = [], 0
        try:
            for stueck in _stuecke(antwort, frist):
                groesse += len(stueck)
                if groesse > max_bytes:
                    raise AbrufFehler(f"Größer als {max_bytes // (1024 * 1024)} MB.")
                teile.append(stueck)
        except AbrufFehler:
            antwort.close()
            raise
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
