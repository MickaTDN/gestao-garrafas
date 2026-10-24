"""Isolated Windows pilot only. Production settings and stock services stay unchanged."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

if os.getenv("GG_WINDOWS_PILOT") != "synthetic-v1" or os.getenv("APP_ENV") != "windows-local":
    raise ImproperlyConfigured("Este perfil exige o piloto sintético Windows explícito.")
if (
    os.getenv("DB_HOST") != "db"
    or os.getenv("DB_NAME") != "garrafas_windows_synthetic"
    or os.getenv("DB_ENGINE", "postgresql") != "postgresql"
):
    raise ImproperlyConfigured("O piloto recusa bases ou servidores externos à sua instalação.")
_secret_root = Path("/run/secrets")
# A secret file is mounted only inside this private container, never in the image.
_pilot_key = (_secret_root / "django_key").read_text().strip()
os.environ["DJANGO_SECRET_KEY"] = _pilot_key
from .settings import *  # noqa: E402,F403

SECRET_KEY = _pilot_key
DEBUG = False
PRODUCTION = False
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
CSRF_TRUSTED_ORIGINS = []  # Same-origin forms; no Wi-Fi origin is authorized.
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_PROXY_SSL_HEADER = None
LOGIN_TRUSTED_PROXY_ADDRESSES = set()
_owner = os.getenv("GG_BOOTSTRAP_OWNER") == "1"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "garrafas_windows_synthetic",
        "HOST": "db",
        "PORT": "5432",
        "USER": "gg_pilot_owner" if _owner else "gg_pilot_app",
        "PASSWORD": (_secret_root / ("db_owner_password" if _owner else "db_app_password"))
        .read_text()
        .strip(),
        "CONN_MAX_AGE": 0,
        "OPTIONS": {"sslmode": "disable", "connect_timeout": 10},
    }
}
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
# Backups in this pilot are synthetic; never misrepresent them as production backups.
