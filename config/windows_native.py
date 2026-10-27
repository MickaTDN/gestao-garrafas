"""Private native Windows profile; loopback only, never adopts a Docker database."""

import json
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

_root = Path(os.environ.get("GVA_DATA_ROOT", ""))
if not _root.is_absolute() or os.environ.get("APP_ENV") != "windows-native":
    raise ImproperlyConfigured("Perfil Windows nativo exige uma instalação explícita.")
_state = json.loads((_root / "installation.json").read_text(encoding="utf-8"))
if _state.get("schema") != 1 or _state.get("postgres_major") != 17 or _state.get("database") not in ("gva_native", "gva_native_synthetic"):
    raise ImproperlyConfigured("Marcador da instalação nativa inválido.")
_owner = os.environ.get("GVA_MAINTENANCE") == "1"
_credentials = json.loads((_root / "secrets" / ("owner.json" if _owner else "app.json")).read_text())
os.environ["DJANGO_SECRET_KEY"] = _credentials["django_key"]
from .settings import *  # noqa: E402,F403

PRODUCTION = False  # Dedicated HTTP-loopback exception; no general production downgrade.
DEBUG = False
SECRET_KEY = _credentials["django_key"]
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
CSRF_TRUSTED_ORIGINS = []
SECURE_PROXY_SSL_HEADER = None
LOGIN_TRUSTED_PROXY_ADDRESSES = set()
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": _state["database"],
    "HOST": "127.0.0.1",
    "PORT": str(_state["db_port"]),
    "USER": _credentials["username"],
    "PASSWORD": _credentials["password"],
    "CONN_MAX_AGE": 0,
    "OPTIONS": {"sslmode": "disable", "connect_timeout": 10},
}}
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_ROOT = _root / "runtime" / "web" / "documents"
VERTENTE_SIGNING_KEY_FILE = str(_root / "signing" / "signing.pem")
