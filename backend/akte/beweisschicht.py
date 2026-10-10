"""Die Beweisschicht der Akte: signierte, verkettete Ereignisse im Format atlas-trace-v1.

* **Sicherung:** Jede fertige Beweissicherung, deren Bytes der Server selbst gesehen hat, wird ein Ereignis, signiert
  mit dem Geräteschlüssel dieser Installation (Datei im Datenordner, nie in der Datenbank).
* **Freigabe:** Ein Mensch gibt eine Karte oder einen Faden frei, indem er im Browser unterschreibt. Der Server
  bereitet das Ereignis vor (``vorbereiten``) und nimmt nur eine gültige Signatur eines nicht widerrufenen
  Menschenschlüssels dieses Kontos an (``abschliessen``). Der Server signiert nie für einen Menschen.
* **Widerruf:** Ein Mensch widerruft einen eigenen Schlüssel mit einem eigenen Schlüssel; spätere Ereignisse dieses
  Schlüssels sind für jeden Prüfer ungültig.
* **Inhalte** stehen nicht im Klartext in der Kette, sondern als Zusage sha256(salz ‖ kanonisches JSON). Salz und
  Inhalt bleiben hier gespeichert und werden mit dem Export offengelegt, sobald das Objekt öffentlich ist. In der
  Nutzlast stehen nur Typ, Objektart und Zusage: keine internen Kennungen, keine Namen, keine Begründungen.
* **Schwärzen** (``manage.py akte_schwaerzen``) löscht Salz und Inhalt eines Ereignisses. Die Kette bleibt gültig,
  der Inhalt lässt sich danach von niemandem mehr offenlegen.

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
from django.db.models import Prefetch
from django.utils import timezone as dj_timezone

from . import lesecache
from .models import Ereignis, Instanz, Schluessel, SchluesselRolle, Status

logger = logging.getLogger(__name__)
VORBEREITUNG_SEKUNDEN = 600
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
#: Attribut, unter dem ``freigaben_prefetch`` die Freigaben eines Objekts ablegt (neueste zuerst).
FREIGABEN_VORAB = "freigaben_vorab"
BEGRUENDUNG_MAX = 2000


class BeweisFehler(Exception):
    """Fachlicher Fehler der Beweisschicht (wird zu 400/403/409)."""

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


# ─── Geräteschlüssel ─────────────────────────────────────────────────────────

def _schluessel_datei() -> Path:
    pfad = getattr(settings, "AKTE_GERAETESCHLUESSEL", "") or ""
    return Path(pfad) if pfad else Path(settings.DATEN_DIR) / "schluessel" / "geraet_ed25519.pem"


def _sicher_schreiben(ziel: Path, daten: bytes) -> None:
    """Neue Datei mit Rechten 600 vollständig schreiben und erst dann unter ihrem Namen sichtbar machen.

    Ein zweiter Prozess, der gleichzeitig anlegt, verliert (Hardlink scheitert an der vorhandenen Datei) und benutzt
    die Datei des ersten. Nie liest jemand eine halb geschriebene Datei.
    """
    tmp = ziel.with_name(f".{ziel.name}.{secrets.token_hex(6)}.neu")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(daten)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(tmp, ziel)
        except FileExistsError:
            pass
        except OSError:
            # Dateisystem ohne Hardlinks: nur anlegen, wenn noch niemand angelegt hat.
            if not ziel.exists():
                os.replace(tmp, ziel)
    finally:
        tmp.unlink(missing_ok=True)


def _schluessel_laden(datei: Path) -> Ed25519PrivateKey:
    for versuch in range(20):
        try:
            privat = load_pem_private_key(datei.read_bytes(), password=None)
        except ValueError:
            if versuch == 19:
                raise
            time.sleep(0.1)
            continue
        if not isinstance(privat, Ed25519PrivateKey):
            raise BeweisFehler(f"{datei} enthält keinen Ed25519-Schlüssel.", 500)
        return privat
    raise AssertionError("unerreichbar")


def geraeteschluessel() -> tuple[str, Ed25519PrivateKey]:
    """Schlüssel dieser Installation laden oder beim ersten Mal anlegen (Datei mit Rechten 600).

    Die Kennung trägt den Fingerabdruck. Wird die Datei ersetzt (Umzug, Verlust), entsteht ein neuer Eintrag im
    Schlüsselbündel; ältere Ereignisse bleiben mit dem alten Schlüssel prüfbar.
    """
    datei = _schluessel_datei()
    if not datei.exists():
        datei.parent.mkdir(parents=True, exist_ok=True)
        neu = Ed25519PrivateKey.generate()
        _sicher_schreiben(datei, neu.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    privat = _schluessel_laden(datei)
    roh = oeffentlicher_schluessel(privat)
    fp = fingerabdruck(roh)
    kid = f"akte-geraet:{fp}"
    s, _ = Schluessel.objects.get_or_create(kid=kid, defaults={"rolle": SchluesselRolle.GERAET, "oeffentlich": b64url(roh),
                                                               "fingerabdruck": fp})
    if s.oeffentlich != b64url(roh):
        raise BeweisFehler("Der Geräteschlüssel passt nicht zum hinterlegten öffentlichen Schlüssel.", 500)
    if s.widerrufen_am:
        raise BeweisFehler("Der Geräteschlüssel ist widerrufen. Datei entfernen, dann entsteht ein neuer.", 500)
    return kid, privat


# ─── Kette ───────────────────────────────────────────────────────────────────

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


def _anhaengen(payload: dict, kid: str, *, signatur_fuer, vorbereitet: dict | None = None, salz: str = "",
               inhalt=None, im_schloss=None, **bezug) -> Ereignis:
    """Ereignis an die Kette hängen (unter Sperre: genau ein Schreiber, genau ein Elternteil).

    ``im_schloss`` läuft nach dem Sperren und vor dem Anhängen: Prüfungen, die zwischen Prüfen und Schreiben nicht
    veralten dürfen (Inhalt unverändert, Prüfbericht gleich).
    """
    with transaction.atomic():
        Instanz.objects.select_for_update().filter(pk=instanz().pk).first()
        if im_schloss is not None:
            im_schloss()
        letzte = Ereignis.objects.order_by("-position").first()
        eltern = [letzte.event_hash] if letzte else []
        if vorbereitet:
            if vorbereitet["eltern"] != eltern:
                raise BeweisFehler("Die Kette hat sich inzwischen verändert. Bitte erneut unterschreiben.", 409,
                                   {"kette_veraendert": True})
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


def _original(q, bevorzugt: set[str]) -> str:
    """SHA-256 der gesicherten Kopie, auf die sich der Beleg stützt. Eine schon unterschriebene Kopie, die noch da
    ist, bleibt maßgeblich; eine spätere zweite Sicherung macht einen Faden nicht „verändert“."""
    kandidaten = [s.sha256 for s in q.sicherungen.all()  # neueste zuerst (Meta.ordering)
                  if s.art in ("original", "anhang") and s.status == "fertig" and s.sha256]
    return next((sha for sha in kandidaten if sha in bevorzugt), kandidaten[0] if kandidaten else "")


def inhalt_faden(v, bevorzugt: set[str] | frozenset = frozenset()) -> dict:
    """Alles, was ein Mensch mit der Freigabe eines Fadens bestätigt: Aussage, Zeitraum, Anhörung und je Beleg die
    Quelle mit Wortlaut und Prüfsumme der gesicherten Kopie."""
    belege = []
    for b in sorted(v.belege.all(), key=lambda b: b.quelle_id):
        q = b.quelle
        belege.append({"quelle": {"titel": q.titel, "url": q.url, "herausgeber": q.herausgeber,
                                  "veroeffentlicht_am": q.veroeffentlicht_am, "abgerufen_am": q.abgerufen_am,
                                  "archiv_url": q.archiv_url, "datei_url": q.datei_url, "guete": q.guete},
                       "zitat_woertlich": b.zitat_woertlich, "fundstelle": b.fundstelle,
                       "original_sha256": _original(q, bevorzugt)})
    return _json({"von": v.von.name, "nach": v.nach.name, "typ": v.typ, "beschreibung": v.beschreibung,
                  "aussageart": v.aussageart, "konfidenz": v.konfidenz, "start": v.start, "ende": v.ende,
                  "aktuell": v.aktuell, "betrag": v.betrag, "waehrung": v.waehrung,
                  "anhoerung_angefragt_am": v.anhoerung_angefragt_am, "anhoerung_antwort": v.anhoerung_antwort,
                  "anhoerung_antwort_am": v.anhoerung_antwort_am, "belege": belege})


def freigaben_prefetch(pfad: str = "ereignisse") -> Prefetch:
    """Für Listen: die Freigaben je Objekt in einer Abfrage statt einer je Objekt (``letzte_freigabe``)."""
    return Prefetch(pfad, queryset=Ereignis.objects.filter(typ="akte.freigabe").order_by("-position"),
                    to_attr=FREIGABEN_VORAB)


def letzte_freigabe(objekt) -> Ereignis | None:
    vorab = getattr(objekt, FREIGABEN_VORAB, None)
    if vorab is not None:
        return vorab[0] if vorab else None
    return objekt.ereignisse.filter(typ="akte.freigabe").order_by("-position").first()


def unterschriebener_inhalt(e: Ereignis) -> dict | None:
    """Der Objekt-Inhalt, den die Freigabe ``e`` bestätigt (None, wenn geschwärzt)."""
    return e.inhalt.get("inhalt") if isinstance(e.inhalt, dict) else None


def _originale(signiert: dict) -> set[str]:
    return {b.get("original_sha256") for b in signiert.get("belege") or [] if isinstance(b, dict)} - {"", None}


def veraendert_seit_freigabe(objekt, art: str) -> bool:
    """Freigegeben, aber der Inhalt stimmt nicht mehr mit dem unterschriebenen überein (oder ist geschwärzt)?"""
    if not aktiv() or objekt.status != Status.FREIGEGEBEN:
        return False
    e = letzte_freigabe(objekt)
    if e is None:
        return False
    signiert = unterschriebener_inhalt(e)
    if signiert is None:
        return True
    jetzt = inhalt_karte(objekt) if art == "karte" else inhalt_faden(objekt, _originale(signiert))
    return kanonisches_json(jetzt) != kanonisches_json(signiert)


# ─── Schlüssel der Menschen ──────────────────────────────────────────────────

def schluessel_anmelden(nutzer, oeffentlich_b64: str) -> Schluessel:
    """Öffentlichen Schlüssel eines Menschen hinterlegen. Die Kennung trägt nur den Fingerabdruck, keinen Namen:
    sie steht im öffentlichen Schlüsselbündel."""
    roh = b64url_lesen(oeffentlich_b64)
    if len(roh) != 32:
        raise BeweisFehler("Ein Ed25519-Schlüssel hat 32 Byte.")
    fp = fingerabdruck(roh)
    kid = f"akte-mensch:{fp}"
    schluessel, neu = Schluessel.objects.get_or_create(kid=kid, defaults={
        "rolle": SchluesselRolle.MENSCH, "nutzer": nutzer, "oeffentlich": b64url(roh), "fingerabdruck": fp})
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


# ─── Vorbereiten und Abschließen (zwei Schritte, der Browser signiert dazwischen) ─────────

def _vorbereiten(nutzer, kid: str, payload: dict, *, zweck: str, salz: str = "", inhalt=None, **zusatz) -> dict:
    letzte = Ereignis.objects.order_by("-position").first()
    v = {"event_id": ulid(), "ts": jetzt_ts(), "eltern": [letzte.event_hash] if letzte else [], "payload": payload,
         "salz": salz, "inhalt": inhalt, "kid": kid, "nutzer": nutzer.pk, "zweck": zweck, **zusatz}
    cache.set(f"akte-beweis:{v['event_id']}", v, VORBEREITUNG_SEKUNDEN)
    eingabe = signing_input(workspace(), v["event_id"], v["ts"], kid, v["eltern"], payload)
    return {"event_id": v["event_id"], "signing_input": b64url(eingabe), "event_hash": hash_hex(eingabe)}


def _vorbereitung(nutzer, event_id: str, zweck: str) -> dict:
    v = cache.get(f"akte-beweis:{event_id}")
    if not v or v["nutzer"] != nutzer.pk or v.get("zweck") != zweck:
        raise BeweisFehler("Vorbereitung abgelaufen oder fremd. Bitte neu beginnen.", 409)
    return v


def _signaturpruefer(schluessel: Schluessel, signatur_b64: str):
    signatur = b64url_lesen(signatur_b64)

    def pruefe(eingabe: bytes) -> bytes:
        if not signatur_gueltig(b64url_lesen(schluessel.oeffentlich), eingabe, signatur):
            raise BeweisFehler("Die Unterschrift passt nicht zu diesem Ereignis.", 400)
        return signatur

    return pruefe


# ─── Freigabe ────────────────────────────────────────────────────────────────

def _pruefbericht(objekt, art: str, begruendungen: dict[str, str], board=None) -> tuple[list[dict], list[str]]:
    """Was der Mensch mit der Freigabe überstimmt und welche Hinweise er offen lässt.

    Jeder sperrende Befund braucht eine Begründung. Auch ein Hinweis lässt sich mit Begründung überstimmen (etwa für
    ein Board, das die Regel strenger einstellt).
    """
    from .pruefung import pruefe_verbindung

    if art != "faden":
        return [], []
    ueber: dict[str, str] = {}
    offen, fehlend = set(), []
    for b in pruefe_verbindung(objekt, board, ohne_zustand=True):
        grund = (begruendungen.get(b.code) or "").strip()[:BEGRUENDUNG_MAX]
        if grund:
            ueber[b.code] = grund
        elif b.schwere == "sperrt":
            fehlend.append({"code": b.code, "text": b.text})
        else:
            offen.add(b.code)
    if fehlend:
        raise BeweisFehler("Sperrende Befunde: zum Überstimmen je eine Begründung angeben.", 400,
                           {"fehlende_begruendung": fehlend})
    return [{"code": c, "begruendung": g} for c, g in sorted(ueber.items())], sorted(offen)


def _objekt_inhalt(objekt, art: str) -> dict:
    return inhalt_karte(objekt) if art == "karte" else inhalt_faden(objekt)


def freigabe_vorbereiten(nutzer, objekt, art: str, kid: str, ueberstimmungen: dict[str, str], board=None) -> dict:
    """Ereignis vorbereiten, das der Mensch im Browser unterschreibt. Gibt die zu signierenden Bytes zurück.

    Unterschrieben wird eine Zusage über ``{objekt, objekt_id, inhalt, hinweise_offen, ueberstimmungen}``. Wird das
    Objekt öffentlich, legt der Export genau das offen, Begründungen eingeschlossen.
    """
    _menschenschluessel(nutzer, kid)
    if objekt.status == Status.FREIGEGEBEN and not veraendert_seit_freigabe(objekt, art):
        raise BeweisFehler("Schon freigegeben und unverändert.", 409)
    ueber, offen = _pruefbericht(objekt, art, ueberstimmungen, board)
    bestaetigt = {"objekt": art, "objekt_id": objekt.pk, "inhalt": _objekt_inhalt(objekt, art),
                  "hinweise_offen": offen, "ueberstimmungen": ueber}
    salz = neues_salz()
    payload = {"type": "akte.freigabe", "objekt": art, "inhalt_zusage": zusage(bestaetigt, salz)}
    antwort = _vorbereiten(nutzer, kid, payload, zweck="freigabe", salz=salz, inhalt=bestaetigt, art=art,
                           objekt_id=objekt.pk, board_id=getattr(board, "pk", None))
    return {**antwort, "inhalt": bestaetigt["inhalt"], "ueberstimmungen": ueber, "hinweise_offen": offen,
            "veroeffentlichung": "Inhalt und Begründungen werden offengelegt, sobald das Objekt öffentlich ist."}


def freigabe_abschliessen(nutzer, event_id: str, signatur_b64: str, objekt_laden) -> Ereignis:
    """Signatur prüfen, Ereignis anhängen, Objekt freigeben – in einer Transaktion.

    Inhalt und Prüfbericht werden unter der Sperre der Kette noch einmal mit dem Vorbereiteten verglichen. Was sich
    danach noch ändert, fällt beim Lesen auf: ``veraendert_seit_freigabe`` vergleicht immer mit dem Unterschriebenen.
    """
    from .models import Board, Entitaet, Ueberstimmung, Verbindung

    v = _vorbereitung(nutzer, event_id, "freigabe")
    schluessel = _menschenschluessel(nutzer, v["kid"])
    pruefe = _signaturpruefer(schluessel, signatur_b64)
    art, bestaetigt = v["art"], v["inhalt"]
    board = Board.objects.filter(pk=v.get("board_id")).first() if v.get("board_id") else None
    gesperrt: dict = {}

    def im_schloss():
        (Verbindung if art == "faden" else Entitaet).objects.select_for_update().filter(pk=v["objekt_id"]).first()
        objekt = objekt_laden(art, v["objekt_id"])
        if kanonisches_json(_objekt_inhalt(objekt, art)) != kanonisches_json(bestaetigt["inhalt"]):
            raise BeweisFehler("Der Inhalt hat sich seit der Vorbereitung geändert. Bitte neu freigeben.", 409)
        begruendungen = {u["code"]: u["begruendung"] for u in bestaetigt["ueberstimmungen"]}
        if _pruefbericht(objekt, art, begruendungen, board) != (bestaetigt["ueberstimmungen"],
                                                                bestaetigt["hinweise_offen"]):
            raise BeweisFehler("Die Prüfung hat sich seit der Vorbereitung geändert. Bitte neu freigeben.", 409)
        gesperrt["objekt"] = objekt

    with transaction.atomic():
        objekt_vorab = objekt_laden(art, v["objekt_id"])
        bezug = {"verbindung": objekt_vorab} if art == "faden" else {"entitaet": objekt_vorab}
        ereignis = _anhaengen(v["payload"], v["kid"], signatur_fuer=pruefe, vorbereitet=v, salz=v["salz"],
                              inhalt=bestaetigt, im_schloss=im_schloss, **bezug)
        objekt = gesperrt["objekt"]
        if art == "faden":
            objekt.ueberstimmungen.all().delete()
            for u in bestaetigt["ueberstimmungen"]:
                Ueberstimmung.objects.create(verbindung=objekt, code=u["code"], begruendung=u["begruendung"],
                                             nutzer=nutzer, ereignis=ereignis)
        type(objekt).objects.filter(pk=objekt.pk).update(status=Status.FREIGEGEBEN, geaendert_am=dj_timezone.now())
        lesecache.veraltet()
    cache.delete(f"akte-beweis:{event_id}")
    return ereignis


# ─── Widerruf ────────────────────────────────────────────────────────────────

def widerruf_vorbereiten(nutzer, kid_widerrufen: str, kid_signierend: str) -> dict:
    """Einen eigenen Schlüssel widerrufen, unterschrieben mit einem eigenen, gültigen Schlüssel (auch demselben).
    Ist der Schlüssel verloren, legt der Browser einen neuen an und unterschreibt damit."""
    ziel = Schluessel.objects.filter(kid=kid_widerrufen, rolle=SchluesselRolle.MENSCH).first()
    if ziel is None or ziel.nutzer_id != nutzer.pk:
        raise BeweisFehler("Unbekannter Schlüssel oder Schlüssel eines anderen Kontos.", 403)
    if ziel.widerrufen_am:
        raise BeweisFehler("Dieser Schlüssel ist schon widerrufen.", 409)
    _menschenschluessel(nutzer, kid_signierend)
    payload = {"type": "akte.widerruf", "kid": kid_widerrufen}
    return {**_vorbereiten(nutzer, kid_signierend, payload, zweck="widerruf", ziel=kid_widerrufen),
            "widerrufen": kid_widerrufen}


def widerruf_abschliessen(nutzer, event_id: str, signatur_b64: str) -> Ereignis:
    v = _vorbereitung(nutzer, event_id, "widerruf")
    schluessel = _menschenschluessel(nutzer, v["kid"])
    pruefe = _signaturpruefer(schluessel, signatur_b64)

    def im_schloss():
        if Schluessel.objects.filter(kid=v["ziel"], widerrufen_am__isnull=False).exists():
            raise BeweisFehler("Dieser Schlüssel ist schon widerrufen.", 409)

    with transaction.atomic():
        ereignis = _anhaengen(v["payload"], v["kid"], signatur_fuer=pruefe, vorbereitet=v, im_schloss=im_schloss)
        Schluessel.objects.filter(kid=v["ziel"]).update(widerrufen_am=dj_timezone.now())
    cache.delete(f"akte-beweis:{event_id}")
    return ereignis


# ─── Schwärzen ───────────────────────────────────────────────────────────────

def schwaerzen(ereignisse) -> int:
    """Salz und Inhalt löschen (z. B. nach einer Unterlassungsverfügung). Die Kette bleibt gültig; offenlegen kann
    den Inhalt danach niemand mehr. Gibt die Zahl der geschwärzten Ereignisse zurück."""
    ids = [e.pk for e in ereignisse]
    with transaction.atomic():
        anzahl = Ereignis.objects.filter(pk__in=ids, geschwaerzt_am__isnull=True).update(
            salz="", inhalt=None, geschwaerzt_am=dj_timezone.now())
        lesecache.veraltet()
    return anzahl


# ─── Export ──────────────────────────────────────────────────────────────────

def export(offenlegen=lambda ereignis: True) -> dict:
    """Ganze Kette als Trace, dazu Schlüsselbündel und die Offenlegung für die gewählten Ereignisse."""
    import json

    ereignisse = list(Ereignis.objects.order_by("position"))
    alle_schluessel = list(Schluessel.objects.all())
    b = buendel({s.kid: b64url_lesen(s.oeffentlich) for s in alle_schluessel},
                instanz().erstellt_am.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    t = trace(workspace(), [json.loads(e.json) for e in ereignisse], b, jetzt_ts())
    offenlegung = {e.event_hash: {"salz": e.salz, "inhalt": e.inhalt}
                   for e in ereignisse if e.salz and e.inhalt is not None and offenlegen(e)}
    widerrufen = {s.kid: s.widerrufen_am.isoformat() for s in alle_schluessel if s.widerrufen_am}
    geschwaerzt = {e.event_hash: e.geschwaerzt_am.isoformat() for e in ereignisse if e.geschwaerzt_am}
    return {"trace": t, "buendel": b, "offenlegung": offenlegung, "widerrufen": widerrufen,
            "geschwaerzt": geschwaerzt}
