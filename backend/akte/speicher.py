"""Privater Speicher für Beweiskopien.

Nach Muster ``atelier/storage.py``, aber mit zwei Unterschieden:

* **eigener, privater Bucket** (``AKTE_R2_BUCKET``), nicht der öffentliche. Kopien
  fremder Artikel sind Arbeitsmaterial der Redaktion und werden nie öffentlich
  weitergegeben; bei öffentlichen Inhalten wäre ein Hash-Schlüssel errechenbar.
* **lokaler Ordner** (``AKTE_SPEICHER_LOKAL``) für die Entwicklung. In Produktion ohne
  Bucket wird nichts gesichert, statt still auf der flüchtigen Container-Platte
  zu landen.

Schlüssel sind inhaltsadressiert (``beweise/<sha256>.<endung>``): dieselbe Datei
liegt nur einmal da, jede Sicherung ist von selbst wiederholbar.
"""

import hashlib
import os
import re
import secrets
from pathlib import Path

import boto3
from django.conf import settings

NAMENSRAUM = "beweise/"


class SpeicherFehlt(Exception):
    pass


class KopieBeschaedigt(Exception):
    """Die gespeicherte Kopie passt nicht mehr zu ihrer Prüfsumme (Datenträgerfehler oder Eingriff)."""


def _r2_eingerichtet() -> bool:
    return bool(
        getattr(settings, "AKTE_R2_BUCKET", "")
        and getattr(settings, "R2_ENDPOINT_URL", "")
        and getattr(settings, "R2_ACCESS_KEY_ID", "")
        and getattr(settings, "R2_SECRET_ACCESS_KEY", "")
    )


def _lokaler_ordner() -> Path | None:
    ordner = getattr(settings, "AKTE_SPEICHER_LOKAL", "")
    return Path(ordner) if ordner else None


def eingerichtet() -> bool:
    return _r2_eingerichtet() or _lokaler_ordner() is not None


def schluessel(sha256: str, endung: str) -> str:
    return f"{NAMENSRAUM}{sha256}.{endung}"


def _pruefe(schl: str) -> str:
    if not schl.startswith(NAMENSRAUM) or ".." in schl or "/" in schl[len(NAMENSRAUM):]:
        raise ValueError(f"unsicherer Schlüssel {schl!r}")
    return schl


def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT_URL,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def ablegen(schl: str, daten: bytes, mime: str) -> None:
    _pruefe(schl)
    if _r2_eingerichtet():
        _client().put_object(Bucket=settings.AKTE_R2_BUCKET, Key=schl, Body=daten, ContentType=mime)
        return
    ordner = _lokaler_ordner()
    if ordner is None:
        raise SpeicherFehlt("Kein Beweis-Speicher eingerichtet (AKTE_R2_BUCKET).")
    ziel = ordner / schl
    ziel.parent.mkdir(parents=True, exist_ok=True)
    if ziel.exists():
        return
    # Erst vollständig in eine Nachbardatei, dann umbenennen: nie eine halbe Kopie unter dem endgültigen Namen.
    tmp = ziel.with_name(f".{ziel.name}.{secrets.token_hex(6)}.neu")
    try:
        with open(tmp, "wb") as f:
            f.write(daten)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, ziel)
    finally:
        tmp.unlink(missing_ok=True)


def _erwartet(schl: str) -> str:
    """Die Schlüssel sind inhaltsadressiert: ``beweise/<sha256>.<endung>``."""
    treffer = re.fullmatch(r"([0-9a-f]{64})\.[A-Za-z0-9]+", schl[len(NAMENSRAUM):])
    return treffer.group(1) if treffer else ""


def lesen(schl: str) -> bytes:
    """Kopie lesen und gegen ihre Prüfsumme halten; eine veränderte Kopie wird nie ausgeliefert."""
    _pruefe(schl)
    if _r2_eingerichtet():
        daten = _client().get_object(Bucket=settings.AKTE_R2_BUCKET, Key=schl)["Body"].read()
    else:
        ordner = _lokaler_ordner()
        if ordner is None:
            raise SpeicherFehlt("Kein Beweis-Speicher eingerichtet (AKTE_R2_BUCKET).")
        daten = (ordner / schl).read_bytes()
    erwartet = _erwartet(schl)
    if erwartet and hashlib.sha256(daten).hexdigest() != erwartet:
        raise KopieBeschaedigt(f"Die Kopie {schl} passt nicht mehr zu ihrer Prüfsumme.")
    return daten
