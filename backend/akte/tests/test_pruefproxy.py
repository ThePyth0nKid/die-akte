"""Der Prüf-Proxy lässt den Browser nur ins offene Internet — auch bei DNS-Tricks."""

import socket
from unittest import mock

from django.test import SimpleTestCase

from akte.pruefproxy import PruefProxy, _verbinden


def _anfrage(adresse: str, zeilen: bytes) -> bytes:
    host, port = adresse.removeprefix("http://").split(":")
    with socket.create_connection((host, int(port)), timeout=5) as s:
        s.sendall(zeilen)
        return s.recv(200)


class PruefProxyTest(SimpleTestCase):
    def test_interne_ziele_werden_abgewiesen(self):
        with PruefProxy() as adresse:
            self.assertIn(b"403", _anfrage(adresse, b"CONNECT 127.0.0.1:443 HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"))
            self.assertIn(b"403", _anfrage(adresse, b"GET http://localhost/ HTTP/1.1\r\nHost: localhost\r\n\r\n"))
            self.assertIn(b"403", _anfrage(adresse, b"CONNECT beispiel.example:6379 HTTP/1.1\r\n\r\n"))

    def test_name_der_auf_intern_zeigt(self):
        # DNS-Rebinding: der Name löst (jetzt) auf eine interne Adresse auf → keine Verbindung.
        intern = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443))]
        with mock.patch("akte.pruefproxy.socket.getaddrinfo", return_value=intern):
            with self.assertRaises(PermissionError):
                _verbinden("harmlos.example", 443)
