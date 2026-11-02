"""Separate HTTPS backend: same DB, isolated secure cookies; never the local listener."""

import json

from .windows_native import *  # noqa: F403
from .windows_native import _root

_wifi = json.loads((_root / "secrets/management-wifi/config.json").read_text())
ALLOWED_HOSTS = [_wifi["hostname"]]
WIFI_ORIGIN = f"https://{_wifi['hostname']}:{_wifi['port']}"
WIFI_PROXY_TOKEN = _wifi["proxy_token"]
WIFI_BACKEND_PORT = _wifi["backend_port"]
CSRF_TRUSTED_ORIGINS = [WIFI_ORIGIN]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_NAME = "gva_wifi_session"
CSRF_COOKIE_NAME = "gva_wifi_csrf"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 3600
USE_X_FORWARDED_HOST = False
MIDDLEWARE = ["config.native_wifi_guard.NativeWifiGuard", *MIDDLEWARE]  # noqa: F405
