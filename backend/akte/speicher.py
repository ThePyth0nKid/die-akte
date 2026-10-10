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

from pathlib import Path

import boto3
from django.conf import settings

NAMENSRAUM = "beweise/"


class SpeicherFehlt(Exception):
    pass


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
    if not ziel.exists():
        ziel.write_bytes(daten)


def lesen(schl: str) -> bytes:
    _pruefe(schl)
    if _r2_eingerichtet():
        return _client().get_object(Bucket=settings.AKTE_R2_BUCKET, Key=schl)["Body"].read()
    ordner = _lokaler_ordner()
    if ordner is None:
        raise SpeicherFehlt("Kein Beweis-Speicher eingerichtet (AKTE_R2_BUCKET).")
    return (ordner / schl).read_bytes()
