"""Einstellungen der Akte.

Alles kommt aus Umgebungsvariablen (siehe ``.env.example`` im Wurzelordner). Ohne weitere Angaben läuft die Akte
lokal auf einem Rechner: SQLite, kein Redis, kein Celery-Dienst, Beweise in einem Ordner neben der Datenbank.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent
DATEN_DIR = Path(os.environ.get("AKTE_DATEN", BASE_DIR.parent / "daten"))


def _schalter(name: str, standard: bool = False) -> bool:
    wert = os.environ.get(name)
    if wert is None or wert == "":
        return standard
    return wert.strip().lower() in {"1", "ja", "true", "an", "on", "yes"}


def _liste(name: str, standard: str = "", trenner: str = ",") -> list[str]:
    return [teil.strip() for teil in os.environ.get(name, standard).split(trenner) if teil.strip()]


DEBUG = _schalter("DJANGO_DEBUG")
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG or os.environ.get("AKTE_TESTLAUF") == "1":
        SECRET_KEY = "nur-fuer-entwicklung-und-tests-nicht-verwenden"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY fehlt. Lege ihn in .env an (siehe .env.example).")

ALLOWED_HOSTS = _liste("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,api,[::1]")
CSRF_TRUSTED_ORIGINS = _liste("DJANGO_CSRF_TRUSTED_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "konto",
    "akte",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "aktesite.urls"
WSGI_APPLICATION = "aktesite.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ─── Datenbank: SQLite als Standard, Postgres über DATABASE_URL ───────────────
DATEN_DIR.mkdir(parents=True, exist_ok=True)
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{(DATEN_DIR / 'akte.sqlite3').as_posix()}",
        conn_max_age=int(os.environ.get("DJANGO_DB_CONN_MAX_AGE", "0")),
    )
}
if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    # WAL + IMMEDIATE: Hintergrund-Threads und Anfragen schreiben gleichzeitig, ohne „database is locked“.
    DATABASES["default"].setdefault("OPTIONS", {}).update(
        {"init_command": "PRAGMA journal_mode=WAL;PRAGMA synchronous=NORMAL;", "transaction_mode": "IMMEDIATE",
         "timeout": 20}
    )

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Cache: Datenbank-Cache, damit die Invalidierung über mehrere Prozesse gilt (lesecache.py).
# Mit REDIS_URL wird Redis benutzt.
if os.environ.get("REDIS_URL"):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache",
                          "LOCATION": os.environ["REDIS_URL"]}}
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache",
                          "LOCATION": "akte_cache"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "de-de"
TIME_ZONE = os.environ.get("AKTE_ZEITZONE", "Europe/Berlin")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = DATEN_DIR / "medien"
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024

# ─── REST: JWT (Web) und Token (Werkzeuge, MCP) ───────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        "anon": os.environ.get("AKTE_DROSSEL_ANON", "60/min"),
        "login": os.environ.get("AKTE_DROSSEL_LOGIN", "10/min"),
        "akte_mitglied": os.environ.get("AKTE_DROSSEL_MITGLIED", "300/hour"),
        "akte_oeffentlich": os.environ.get("AKTE_DROSSEL_OEFFENTLICH", "120/min"),
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.environ.get("AKTE_JWT_MINUTEN", "30"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(os.environ.get("AKTE_JWT_REFRESH_TAGE", "14"))),
    "ROTATE_REFRESH_TOKENS": True,
    "UPDATE_LAST_LOGIN": True,
}

# ─── Celery (optional) ────────────────────────────────────────────────────────
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", os.environ.get("REDIS_URL", "memory://"))
CELERY_RESULT_BACKEND = None
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_ALWAYS_EAGER = _schalter("AKTE_CELERY_EAGER", not os.environ.get("REDIS_URL"))
CELERY_TASK_EAGER_PROPAGATES = False

# ─── Die Akte ─────────────────────────────────────────────────────────────────
# Lesen ohne Konto: aus, bis du bewusst einschaltest.
AKTE_OEFFENTLICH_AKTIV = _schalter("AKTE_OEFFENTLICH_AKTIV")
# Boards, die jedes angemeldete Konto lesen darf (kommagetrennte Slugs). Leer = aus.
AKTE_MITGLIEDER_BOARDS = os.environ.get("AKTE_MITGLIEDER_BOARDS", "")

# Beweissicherung: S3-kompatibler Bucket (privat!) oder ein lokaler Ordner. Standard: Ordner unter daten/.
AKTE_S3_BUCKET = os.environ.get("AKTE_S3_BUCKET", os.environ.get("AKTE_R2_BUCKET", ""))
AKTE_R2_BUCKET = AKTE_S3_BUCKET  # Altname, von speicher.py gelesen
R2_ENDPOINT_URL = os.environ.get("AKTE_S3_ENDPOINT_URL", os.environ.get("R2_ENDPOINT_URL", ""))
R2_ACCESS_KEY_ID = os.environ.get("AKTE_S3_ACCESS_KEY_ID", os.environ.get("R2_ACCESS_KEY_ID", ""))
R2_SECRET_ACCESS_KEY = os.environ.get("AKTE_S3_SECRET_ACCESS_KEY", os.environ.get("R2_SECRET_ACCESS_KEY", ""))
AKTE_SPEICHER_LOKAL = os.environ.get(
    "AKTE_SPEICHER_LOKAL", "" if AKTE_S3_BUCKET else str(DATEN_DIR / "beweise")
)
_SPEICHER_DA = bool(AKTE_S3_BUCKET or AKTE_SPEICHER_LOKAL)
AKTE_SICHERUNG_AKTIV = _schalter("AKTE_SICHERUNG_AKTIV", _SPEICHER_DA)
# Seitenbild und Fundstellen in Webseiten brauchen Chromium (Playwright). PDFs gehen ohne.
AKTE_BROWSER_AKTIV = _schalter("AKTE_BROWSER_AKTIV", False)
# Optional: archive.org-Schlüssel "zugang:geheim" für die zuverlässige Save-Page-Now-API.
AKTE_ARCHIVE_ORG_SCHLUESSEL = os.environ.get("AKTE_ARCHIVE_ORG_SCHLUESSEL", "")
# O-Ton-Einspieler in Fahrten dürfen nur aus diesen Ordnern kommen (Trenner ";"). Leer = Funktion aus.
AKTE_EINSPIELER_WURZELN = _liste("AKTE_EINSPIELER_WURZELN", "", ";")
# Kennung beim Abruf fremder Seiten (bitte mit Kontakt-URL deiner Instanz).
AKTE_ABRUF_KENNUNG = os.environ.get(
    "AKTE_ABRUF_KENNUNG", "Die-Akte/0.1 (+https://github.com/ThePyth0nKid/die-akte)"
)
# Echte Besucher-IP für die Drossel ohne Konto (permissions.AkteOeffentlichThrottle.get_ident):
# Kopf eines vorgeschalteten Dienstes (z. B. CF-Connecting-IP) und/oder Zahl der eigenen Proxys vor der API.
AKTE_CLIENT_IP_HEADER = os.environ.get("AKTE_CLIENT_IP_HEADER", "")
AKTE_VERTRAUTE_PROXYS = int(os.environ.get("AKTE_VERTRAUTE_PROXYS", "0"))

# ─── Testlauf: keine fremden Seiten, keine Drosseln, schneller Hash ───────────
if os.environ.get("AKTE_TESTLAUF") == "1":
    AKTE_SICHERUNG_AKTIV = False
    AKTE_BROWSER_AKTIV = False
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"konsole": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["konsole"], "level": os.environ.get("AKTE_LOGLEVEL", "INFO")},
}
