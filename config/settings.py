"""Configuration shared by development, tests and a future production deployment."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=False)

PRODUCTION = os.getenv("APP_ENV", "development") == "production"
DEBUG = os.getenv("DJANGO_DEBUG", "0" if PRODUCTION else "1") == "1"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    raise ImproperlyConfigured("Defina DJANGO_SECRET_KEY ou execute python3 scripts/bootstrap.py.")
if PRODUCTION and DEBUG:
    raise ImproperlyConfigured("DJANGO_DEBUG deve ser 0 em produção.")
ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",")
    if h.strip()
]
CSRF_TRUSTED_ORIGINS = [
    h.strip() for h in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "inventory",
    "imports",
    "web",
    "consultation",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "config.middleware.PrivacyMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

if os.getenv("DB_ENGINE", "postgresql") == "sqlite":
    if PRODUCTION:
        raise ImproperlyConfigured("Produção requer PostgreSQL.")
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "private" / "dev.sqlite3",
    }}
else:
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "garrafas"),
        "USER": os.getenv("DB_USER", "garrafas"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", "5432"),
        "CONN_MAX_AGE": 60 if PRODUCTION else 0,
        "OPTIONS": {"sslmode": os.getenv("DB_SSLMODE", "verify-full" if PRODUCTION else "prefer")},
    }}
if os.getenv("DB_TEST_NAME"):
    DATABASES["default"]["TEST"] = {"NAME": os.environ["DB_TEST_NAME"]}

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "login"
LANGUAGE_CODE = "pt-pt"
TIME_ZONE = "Europe/Lisbon"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": (
        "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if PRODUCTION else "django.contrib.staticfiles.storage.StaticFilesStorage"
    )},
}
# Never add a public MEDIA_URL or serve private documents via staticfiles.
MEDIA_ROOT = BASE_DIR / "private" / "documents"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = PRODUCTION
CSRF_COOKIE_SECURE = PRODUCTION
SECURE_SSL_REDIRECT = PRODUCTION
SECURE_HSTS_SECONDS = 31536000 if PRODUCTION else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = PRODUCTION
SECURE_HSTS_PRELOAD = PRODUCTION
X_FRAME_OPTIONS = "DENY"
# Only set this behind a reverse proxy that removes incoming spoofed headers.
if os.getenv("TRUST_HTTPS_PROXY", "0") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Bounded uploads and database-backed login protection, shared by all workers.
DATA_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 256 * 1024
LOGIN_ACCOUNT_LIMIT = int(os.getenv("LOGIN_ACCOUNT_LIMIT", "5"))
LOGIN_ADDRESS_LIMIT = int(os.getenv("LOGIN_ADDRESS_LIMIT", "30"))
LOGIN_WINDOW_SECONDS = int(os.getenv("LOGIN_WINDOW_SECONDS", "900"))
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SECURE_REFERRER_POLICY = "same-origin"

LOGIN_TRUSTED_PROXY_ADDRESSES = {address.strip() for address in os.getenv("LOGIN_TRUSTED_PROXY_ADDRESSES", "").split(",") if address.strip()}
VERTENTE_SIGNING_KEY_FILE = os.getenv("VERTENTE_SIGNING_KEY_FILE", "")
