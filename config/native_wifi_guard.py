"""Loopback alone is not a trusted proxy: require an installation-specific secret."""

import hmac

from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest


class NativeWifiGuard:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.META.get("REMOTE_ADDR") != "127.0.0.1"
            or request.META.get("HTTP_X_FORWARDED_PROTO") != "https"
            or request.META.get("HTTP_HOST") != settings.WIFI_ORIGIN.removeprefix("https://")
            or not hmac.compare_digest(
                request.META.get("HTTP_X_GVA_PROXY", "").encode(),
                settings.WIFI_PROXY_TOKEN.encode(),
            )
        ):
            return HttpResponseBadRequest("Proxy HTTPS não autorizado.")
        # Not a public readiness endpoint: the proxy denies this path.
        if request.path == "/_native_wifi_ready" and request.method == "GET":
            return HttpResponse("ready")
        return self.get_response(request)
