"""Die Beweisschicht der Akte: signierte, verkettete Ereignisse im Format atlas-trace-v1.

* **Sicherung:** Jede fertige Beweissicherung wird ein Ereignis, signiert mit dem Geräteschlüssel dieser
  Installation (Datei im Datenordner, nie in der Datenbank).
* **Freigabe:** Ein Mensch gibt eine Karte oder einen Faden frei, indem er im Browser unterschreibt. Der Server
  bereitet das Ereignis vor (``vorbereiten``) und nimmt nur eine gültige Signatur eines nicht widerrufenen
  Menschenschlüssels dieses Kontos an (``abschliessen``). Der Server signiert nie für einen Menschen.
* **Inhalte** stehen nicht im Klartext in der Kette, sondern als Zusage sha256(salz ‖ kanonisches JSON). Salz und
  Inhalt bleiben hier gespeichert und werden mit dem Export offengelegt, sobald das Objekt öffentlich ist.

Die Kette ist linear (genau ein Elternteil je Ereignis) und lässt sich mit ``atlas-verify-cli --require-strict-chain``
oder ``akte pruefe-signaturen`` ohne Server prüfen.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from akte_beweis import (
    b64url,
    b64url_lesen,
    buendel,
    ereignis_aus_signatur,
    fingerabdruck,
    hash_hex,
    neues_salz,
    oeffentlicher_schluessel,
    signieren,
    signing_input,
    trace,
    zusage,
)
from akte_beweis.atlas import signatur_gueltig
from akte_beweis.kanonisch import kanonisches_json
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    load_pem_private_key,
)
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone as dj_timezone

from .models import Ereignis, Instanz, Schluessel, SchluesselRolle, Status

logger = logging.getLogger(__name__)
VORBEREITUNG_SEKUNDEN = 600
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


class BeweisFehler(Exception):
    """Fachlicher Fehler der Beweisschicht (wird zu 400/409)."""

    def __init__(self, text: str, status: int = 400, daten: dict | None = None):
        super().__init__(text)
        self.status = status
        self.daten = daten or {}


# ─── Grundlagen ──────────────────────────────────────────────────────────────

def aktiv() -> bool:
    return bool(getattr(settings, "AKTE_BEWEISSCHICHT", True))


def ulid() -> str:
    """Zeitlich sortierbare Kennung: 48 Bit Millisekunden + 80 Bit Zufall, Crockford-Base32."""
    zahl = (int(time.time() * 1000) << 80) | secrets.randbits(80)
    return "".join(_CROCKFORD[(zahl >> (5 * i)) & 31] for i in range(25, -1, -1))


def jetzt_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def instanz() -> Instanz:
    obj = Instanz.objects.first()
    if obj is None:
        obj, _ = Instanz.objects.get_or_create(pk=1, defaults={"kennung": uuid.uuid4()})
    return obj


def workspace() -> str:
    return f"akte:{instanz().kennung}"


def _schluessel_datei() -> Path:
    pfad = getattr(settings, "AKTE_GERAETESCHLUESSEL", "") or ""
    return Path(pfad) if pfad else Path(settings.DATEN_DIR) / "schluessel" / "geraet_ed25519.pem"


def geraeteschluessel() -> tuple[str, Ed25519PrivateKey]:
    """Schlüssel dieser Installation laden oder beim ersten Mal anlegen (Datei mit Rechten 600)."""
    datei = _schluessel_datei()
    if datei.exists():
        privat = load_pem_private_key(datei.read_bytes(), password=None)
    else:
        datei.parent.mkdir(parents=True, exist_ok=True)
        privat = Ed25519PrivateKey.generate()
        pem = privat.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        fd = os.open(datei, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(pem)
    roh = oeffentlicher_schluessel(privat)
    kid = f"akte-geraet:{str(instanz().kennung)[:8]}"
    Schluessel.objects.get_or_create(kid=kid, defaults={"rolle": SchluesselRolle.GERAET, "oeffentlich": b64url(roh),
                                                        "fingerabdruck": fingerabdruck(roh)})
    return kid, privat


def _json(wert) -> object:
    """Daten für Zusagen: Datum und Dezimalzahl als Zeichenkette (keine Gleitkommazahlen)."""
    if isinstance(wert, dict):
        return {str(k): _json(v) for k, v in wert.items()}
    if isinstance(wert, (list, tuple)):
        return [_json(v) for v in wert]
    if isinstance(wert, (Decimal, float)):
        return str(wert)
    if hasattr(wert, "isoformat"):
        return wert.isoformat()
    return wert


def _anhaengen(payload: dict, kid: str, *, signatur_fuer=None, vorbereitet: dict | None = None,
               salz: str = "", inhalt=None, **bezug) -> Ereignis:
    """Ereignis an die Kette hängen (unter Sperre: genau ein Schreiber, genau ein Elternteil)."""
    with transaction.atomic():
        Instanz.objects.select_for_update().filter(pk=instanz().pk).first()
        letzte = Ereignis.objects.order_by("-position").first()
        eltern = [letzte.event_hash] if letzte else []
        if vorbereitet:
            if vorbereitet["eltern"] != eltern:
                raise BeweisFehler("Die Kette hat sich inzwischen verändert. Bitte erneut unterschreiben.", 409)
            event_id, ts = vorbereitet["event_id"], vorbereitet["ts"]
        else:
            event_id, ts = ulid(), jetzt_ts()
        eingabe = signing_input(workspace(), event_id, ts, kid, eltern, payload)
        signatur = signatur_fuer(eingabe)
        e = ereignis_aus_signatur(eingabe, signatur, event_id=event_id, ts=ts, kid=kid, eltern=eltern, payload=payload)
        return Ereignis.objects.create(
            position=(letzte.position + 1) if letzte else 1, event_id=event_id, event_hash=e["event_hash"],
            typ=payload["type"], kid=kid, json=kanonisches_json(e).decode("utf-8"), salz=salz, inhalt=inhalt, **bezug)


# ─── Sicherungen ─────────────────────────────────────────────────────────────

def sicherung_eintragen(sicherung) -> Ereignis | None:
    """Fertige Sicherung als signiertes Ereignis. Scheitert das, bleibt die Sicherung trotzdem bestehen."""
    if not aktiv() or not (sicherung.sha256 or sicherung.fremd_url):
        return None
    try:
        kid, privat = geraeteschluessel()
        q = sicherung.quelle
        inhalt = _json({"quelle": {"titel": q.titel, "url": q.url, "herausgeber": q.herausgeber},
                        "art": sicherung.art, "sha256": sicherung.sha256, "bytes": sicherung.bytes,
                        "mime": sicherung.mime, "fremd_url": sicherung.fremd_url,
                        "gesichert_am": sicherung.gesichert_am})
        salz = neues_salz()
        payload = {"type": "akte.sicherung", "art": sicherung.art, "inhalt_zusage": zusage(inhalt, salz)}
        return _anhaengen(payload, kid, signatur_fuer=privat.sign, salz=salz, inhalt=inhalt, sicherung=sicherung)
    except Exception:  # noqa: BLE001 — die Beweissicherung selbst darf an der Kette nie scheitern
        logger.exception("Akte: Sicherung %s nicht in die Kette eingetragen", sicherung.pk)
        return None


# ─── Inhalte von Karten und Fäden ─────────────────────────────────────────────

def inhalt_karte(e) -> dict:
    return _json({"name": e.name, "typ": e.typ, "kurzbeschreibung": e.kurzbeschreibung,
                  "oeffentliche_person": e.oeffentliche_person, "bild_url": e.bild_url,
                  "bild_nachweis": e.bild_nachweis})


def inhalt_faden(v) -> dict:
    belege = []
    for b in sorted(v.belege.all(), key=lambda b: b.quelle_id):
        q = b.quelle
        original = next((s.sha256 for s in q.sicherungen.all() if s.art in ("original", "anhang")
                         and s.status == "fertig" and s.sha256), "")
        belege.append({"quelle": {"titel": q.titel, "url": q.url, "herausgeber": q.herausgeber,
                                  "abgerufen_am": q.abgerufen_am, "archiv_url": q.archiv_url},
                       "zitat_woertlich": b.zitat_woertlich, "fundstelle": b.fundstelle, "original_sha256": original})
    return _json({"von": v.von.name, "nach": v.nach.name, "typ": v.typ, "beschreibung": v.beschreibung,
                  "aussageart": v.aussageart, "start": v.start, "ende": v.ende, "aktuell": v.aktuell,
                  "betrag": v.betrag, "waehrung": v.waehrung, "belege": belege})


def letzte_freigabe(objekt) -> Ereignis | None:
    return objekt.ereignisse.filter(typ="akte.freigabe").order_by("-position").first()


def veraendert_seit_freigabe(objekt, art: str) -> bool:
    """Freigegeben, aber der Inhalt stimmt nicht mehr mit dem unterschriebenen überein?"""
    if not aktiv() or objekt.status != Status.FREIGEGEBEN:
        return False
    e = letzte_freigabe(objekt)
    if e is None:
        return False
    jetzt = inhalt_karte(objekt) if art == "karte" else inhalt_faden(objekt)
    return kanonisches_json(jetzt) != kanonisches_json(e.inhalt)


# ─── Schlüssel der Menschen ──────────────────────────────────────────────────

def schluessel_anmelden(nutzer, oeffentlich_b64: str) -> Schluessel:
    roh = b64url_lesen(oeffentlich_b64)
    if len(roh) != 32:
        raise BeweisFehler("Ein Ed25519-Schlüssel hat 32 Byte.")
    fp = fingerabdruck(roh)
    kid = f"akte-mensch:{nutzer.get_username()}#{fp}"
    schluessel, neu = Schluessel.objects.get_or_create(kid=kid, defaults={
        "rolle": SchluesselRolle.MENSCH, "nutzer": nutzer, "oeffentlich": oeffentlich_b64, "fingerabdruck": fp})
    if not neu and (schluessel.nutzer_id != nutzer.pk or schluessel.widerrufen_am):
        raise BeweisFehler("Dieser Schlüssel gehört zu einem anderen Konto oder ist widerrufen.", 409)
    return schluessel


def _menschenschluessel(nutzer, kid: str) -> Schluessel:
    s = Schluessel.objects.filter(kid=kid, rolle=SchluesselRolle.MENSCH).first()
    if s is None or s.nutzer_id != nutzer.pk:
        raise BeweisFehler("Unbekannter Schlüssel oder Schlüssel eines anderen Kontos.", 403)
    if s.widerrufen_am:
        raise BeweisFehler("Dieser Schlüssel ist widerrufen.", 403)
    return s


# ─── Freigabe in zwei Schritten ──────────────────────────────────────────────

def freigabe_vorbereiten(nutzer, objekt, art: str, kid: str, ueberstimmungen: dict[str, str]) -> dict:
    """Ereignis vorbereiten, das der Mensch im Browser unterschreibt. Gibt die zu signierenden Bytes zurück."""
    from .pruefung import pruefe_verbindung

    _menschenschluessel(nutzer, kid)
    if objekt.status == Status.FREIGEGEBEN and not veraendert_seit_freigabe(objekt, art):
        raise BeweisFehler("Schon freigegeben und unverändert.", 409)
    payload_ueber, offen = [], []
    if art == "faden":
        befunde = [b for b in pruefe_verbindung(objekt, ohne_zustand=True)]
        fehlend = []
        for b in befunde:
            if b.schwere == "sperrt":
                grund = (ueberstimmungen.get(b.code) or "").strip()
                if not grund:
                    fehlend.append({"code": b.code, "text": b.text})
                    continue
                payload_ueber.append({"code": b.code, "begruendung": grund})
            else:
                offen.append(b.code)
        if fehlend:
            raise BeweisFehler("Sperrende Befunde: zum Überstimmen je eine Begründung angeben.", 400,
                               {"fehlende_begruendung": fehlend})
        inhalt = inhalt_faden(objekt)
    else:
        inhalt = inhalt_karte(objekt)
    salz = neues_salz()
    payload = {"type": "akte.freigabe", "objekt": art, "objekt_id": objekt.pk, "inhalt_zusage": zusage(inhalt, salz),
               "hinweise_offen": sorted(set(offen)),
               "ueberstimmungen": [{"code": u["code"], "begruendung_zusage": zusage(u["begruendung"], salz)}
                                   for u in payload_ueber]}
    letzte = Ereignis.objects.order_by("-position").first()
    vorbereitet = {"event_id": ulid(), "ts": jetzt_ts(), "eltern": [letzte.event_hash] if letzte else [],
                   "payload": payload, "salz": salz, "inhalt": inhalt, "kid": kid, "nutzer": nutzer.pk,
                   "art": art, "objekt_id": objekt.pk, "ueberstimmungen": payload_ueber}
    cache.set(f"akte-freigabe:{vorbereitet['event_id']}", vorbereitet, VORBEREITUNG_SEKUNDEN)
    eingabe = signing_input(workspace(), vorbereitet["event_id"], vorbereitet["ts"], kid, vorbereitet["eltern"],
                            payload)
    return {"event_id": vorbereitet["event_id"], "signing_input": b64url(eingabe),
            "event_hash": hash_hex(eingabe), "inhalt": inhalt, "ueberstimmungen": payload_ueber,
            "hinweise_offen": payload["hinweise_offen"]}


def freigabe_abschliessen(nutzer, event_id: str, signatur_b64: str, objekt_laden) -> Ereignis:
    """Signatur prüfen, Ereignis anhängen, Objekt freigeben – in einer Transaktion."""
    from .models import Ueberstimmung

    vorbereitet = cache.get(f"akte-freigabe:{event_id}")
    if not vorbereitet or vorbereitet["nutzer"] != nutzer.pk:
        raise BeweisFehler("Vorbereitung abgelaufen oder fremd. Bitte neu freigeben.", 409)
    schluessel = _menschenschluessel(nutzer, vorbereitet["kid"])
    signatur = b64url_lesen(signatur_b64)
    objekt = objekt_laden(vorbereitet["art"], vorbereitet["objekt_id"])
    aktuell = inhalt_karte(objekt) if vorbereitet["art"] == "karte" else inhalt_faden(objekt)
    if kanonisches_json(aktuell) != kanonisches_json(vorbereitet["inhalt"]):
        raise BeweisFehler("Der Inhalt hat sich seit der Vorbereitung geändert. Bitte neu freigeben.", 409)

    def pruefe_signatur(eingabe: bytes) -> bytes:
        if not signatur_gueltig(b64url_lesen(schluessel.oeffentlich), eingabe, signatur):
            raise BeweisFehler("Die Unterschrift passt nicht zu diesem Ereignis.", 400)
        return signatur

    bezug = {"verbindung": objekt} if vorbereitet["art"] == "faden" else {"entitaet": objekt}
    with transaction.atomic():
        ereignis = _anhaengen(vorbereitet["payload"], vorbereitet["kid"], signatur_fuer=pruefe_signatur,
                              vorbereitet=vorbereitet, salz=vorbereitet["salz"], inhalt=vorbereitet["inhalt"], **bezug)
        if vorbereitet["art"] == "faden":
            objekt.ueberstimmungen.all().delete()
            for u in vorbereitet["ueberstimmungen"]:
                Ueberstimmung.objects.create(verbindung=objekt, code=u["code"], begruendung=u["begruendung"],
                                             nutzer=nutzer, ereignis=ereignis)
        type(objekt).objects.filter(pk=objekt.pk).update(status=Status.FREIGEGEBEN, geaendert_am=dj_timezone.now())
    cache.delete(f"akte-freigabe:{event_id}")
    return ereignis


# ─── Export ──────────────────────────────────────────────────────────────────

def export(offenlegen=lambda ereignis: True) -> dict:
    """Ganze Kette als Trace, dazu Schlüsselbündel und die Offenlegung für die gewählten Ereignisse."""
    import json

    ereignisse = list(Ereignis.objects.order_by("position"))
    schluessel = {s.kid: b64url_lesen(s.oeffentlich) for s in Schluessel.objects.all()}
    b = buendel(schluessel, instanz().erstellt_am.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    t = trace(workspace(), [json.loads(e.json) for e in ereignisse], b, jetzt_ts())
    offenlegung = {}
    for e in ereignisse:
        if e.salz and e.inhalt is not None and offenlegen(e):
            eintrag = {"salz": e.salz, "inhalt": e.inhalt}
            ueber = list(e.verbindung.ueberstimmungen.filter(ereignis=e)) if e.verbindung_id else []
            if ueber:
                eintrag["ueberstimmungen"] = [{"code": u.code, "begruendung": u.begruendung} for u in ueber]
            offenlegung[e.event_hash] = eintrag
    widerrufen = {s.kid: s.widerrufen_am.isoformat() for s in Schluessel.objects.exclude(widerrufen_am=None)}
    return {"trace": t, "buendel": b, "offenlegung": offenlegung, "widerrufen": widerrufen}
