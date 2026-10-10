"""Prüf-Proxy für den Browser der Beweissicherung.

Chromium löst Adressen selbst auf. Eine Prüfung vorher in Python (``route``) hilft nicht gegen
DNS-Rebinding: Zwischen Prüfung und Verbindung kann ein Angreifer seinen Namen auf eine interne
Adresse umbiegen. Deshalb läuft **jede** Verbindung des Browsers über diesen kleinen Proxy auf
127.0.0.1. Er löst den Namen selbst auf, lässt nur öffentliche Adressen zu und verbindet sich
genau mit der IP, die er geprüft hat — für HTTPS (CONNECT), WebSockets (ebenfalls CONNECT) und
einfaches HTTP. Chromium startet mit ``--proxy-bypass-list=<-loopback>``, damit auch
``localhost`` nicht am Proxy vorbeigeht.
"""

import select
import socket
import socketserver
import threading
from urllib.parse import urlsplit

from .abruf import ERLAUBTE_PORTS, oeffentlich

ZEITLIMIT = 30
KOPF_MAX = 64 * 1024


def _verbinden(host: str, port: int) -> socket.socket:
    if port not in ERLAUBTE_PORTS:
        raise PermissionError(f"Port {port} gesperrt")
    adressen = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not adressen or not all(oeffentlich(a[4][0]) for a in adressen):
        raise PermissionError(f"{host} zeigt nicht ins offene Internet")
    familie, art, proto, _, ziel = adressen[0]
    sock = socket.socket(familie, art, proto)
    sock.settimeout(ZEITLIMIT)
    sock.connect(ziel)  # genau die geprüfte IP, keine zweite Auflösung
    if not oeffentlich(sock.getpeername()[0]):
        sock.close()
        raise PermissionError("Gegenstelle nicht öffentlich")
    return sock


def _weiterreichen(a: socket.socket, b: socket.socket) -> None:
    paar = [a, b]
    while True:
        lesbar, _, fehler = select.select(paar, [], paar, ZEITLIMIT)
        if fehler or not lesbar:
            return
        for quelle in lesbar:
            daten = quelle.recv(64 * 1024)
            if not daten:
                return
            (b if quelle is a else a).sendall(daten)


class _Anfrage(socketserver.BaseRequestHandler):
    def handle(self):
        client = self.request
        client.settimeout(ZEITLIMIT)
        kopf = b""
        while b"\r\n\r\n" not in kopf:
            stueck = client.recv(4096)
            if not stueck or len(kopf) > KOPF_MAX:
                return
            kopf += stueck
        kopfteil, _, rest = kopf.partition(b"\r\n\r\n")
        zeilen = kopfteil.split(b"\r\n")
        try:
            methode, ziel, version = zeilen[0].decode("latin-1").split(" ", 2)
        except ValueError:
            return
        try:
            if methode.upper() == "CONNECT":
                host, _, port = ziel.rpartition(":")
                entfernt = _verbinden(host.strip("[]"), int(port))
                client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                if rest:
                    entfernt.sendall(rest)
            else:
                teile = urlsplit(ziel)
                if teile.scheme != "http" or not teile.hostname:
                    raise PermissionError("nur absolute http-Adressen")
                entfernt = _verbinden(teile.hostname, teile.port or 80)
                pfad = (teile.path or "/") + (f"?{teile.query}" if teile.query else "")
                # Eine Anfrage je Verbindung: sonst schickte Chromium die nächste Anfrage an einen
                # anderen Host über denselben, schon geprüften Tunnel.
                koepfe = [z for z in zeilen[1:] if not z.lower().startswith((b"connection:", b"proxy-connection:", b"keep-alive:"))]
                neu = [f"{methode} {pfad} {version}".encode("latin-1"), *koepfe, b"Connection: close"]
                entfernt.sendall(b"\r\n".join(neu) + b"\r\n\r\n" + rest)
        except (PermissionError, OSError, ValueError):
            try:
                client.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            return
        try:
            _weiterreichen(client, entfernt)
        finally:
            entfernt.close()


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class PruefProxy:
    """``with PruefProxy() as adresse:`` — Proxy auf einem freien Port, nur für diesen Lauf."""

    def __enter__(self) -> str:
        self._server = _Server(("127.0.0.1", 0), _Anfrage)
        self._faden = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._faden.start()
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def __exit__(self, *_):
        self._server.shutdown()
        self._server.server_close()
