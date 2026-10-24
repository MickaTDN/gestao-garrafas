"""Company Wi-Fi rehearsal, with a NEW synthetic database and an authenticated TLS proxy."""

import ipaddress
import os
import re

from django.core.exceptions import ImproperlyConfigured

# Reuse the isolated DB/secret/role contract; never adopt a production target.
from .windows_local import *  # noqa: F403

if os.getenv("GG_ANDROID_WIFI") != "synthetic-wifi-v1":
    raise ImproperlyConfigured("O perfil Android exige uma instalação Wi-Fi sintética explícita.")
_host = os.getenv("GG_WIFI_HOST", "")
if (
    len(_host) > 253
    or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", _host)
    or "." not in _host
    or any(
        not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
        for label in _host.split(".")
    )
):
    raise ImproperlyConfigured("Defina um único nome DNS interno aprovado, sem porta ou wildcard.")
try:
    ipaddress.ip_address(_host)
except ValueError:
    pass
else:
    raise ImproperlyConfigured("Use o nome DNS constante do certificado, não um endereço IP.")
_port = os.getenv("GG_HTTPS_PORT", "8443")
if not _port.isdecimal() or not 1024 <= int(_port) <= 65535:
    raise ImproperlyConfigured("Porta HTTPS inválida.")
try:
    _proxy = ipaddress.IPv4Address(os.environ["GG_PROXY_IP"])
    _app = ipaddress.IPv4Address(os.environ["GG_APP_IP"])
    _network = ipaddress.IPv4Network(os.environ["GG_PROXY_SUBNET"])
    _private_ranges = [
        ipaddress.IPv4Network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    ]
    if (
        _network.prefixlen != 29
        or not any(_network.subnet_of(value) for value in _private_ranges)
        or _proxy != _network.network_address + 2
        or _app != _network.network_address + 3
    ):
        raise ValueError
except (KeyError, ValueError) as error:
    raise ImproperlyConfigured("Defina a rede interna /29 e o IP exclusivo do proxy.") from error

DEBUG = False
ALLOWED_HOSTS = [_host]
WIFI_ORIGIN = f"https://{_host}:{_port}"
CSRF_TRUSTED_ORIGINS = [WIFI_ORIGIN]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = False
LOGIN_TRUSTED_PROXY_ADDRESSES = {str(_proxy)}
WIFI_PROXY_ADDRESS = str(_proxy)
MIDDLEWARE = ["config.wifi_middleware.WifiProxyMiddleware", *MIDDLEWARE]  # noqa: F405
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
