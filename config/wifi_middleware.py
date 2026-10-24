from django.conf import settings
from django.http import HttpResponseBadRequest


class WifiProxyMiddleware:
    """Only the isolated proxy can assert HTTPS or a client address."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.META.get("REMOTE_ADDR") != settings.WIFI_PROXY_ADDRESS
            or request.META.get("HTTP_X_FORWARDED_PROTO") != "https"
            or request.META.get("HTTP_HOST") != settings.WIFI_ORIGIN.removeprefix("https://")
        ):
            return HttpResponseBadRequest("Acesso permitido apenas pelo proxy HTTPS autorizado.")
        return self.get_response(request)
