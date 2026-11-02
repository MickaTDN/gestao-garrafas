"""Distinct device-only backend; no login, admin views or session middleware."""

import json

from .windows_native import *  # noqa: F403
from .windows_native import _root

SHEET_RECEIVER = json.loads((_root / "secrets/sheet-receiver/config.json").read_text())
SHEET_RECEIVER["root"] = str(_root)
SHEET_RECEIVER["enabled"] = True  # Runtime guard additionally requires destination approval.
ALLOWED_HOSTS = [SHEET_RECEIVER["hostname"]]
ROOT_URLCONF = "config.sheet_receiver_urls"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = False
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
MIDDLEWARE = [
    "config.sheet_receiver_guard.SheetReceiverGuard",
    "django.middleware.security.SecurityMiddleware",
]
