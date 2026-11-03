"""Keep requests away from a recovery candidate until its durable commit point."""

from pathlib import Path

from django.conf import settings
from django.http import HttpResponse


class NativeMaintenanceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        marker = getattr(settings, "NATIVE_MAINTENANCE_FILE", None)
        if marker and Path(marker).exists():
            # Only the cookieless login-page GET used by health_http may reach
            # Django. It cannot authenticate, export stock, confirm an operation
            # or write user state. An activation permit is NOT a write permit.
            health = (
                request.method == "GET"
                and request.path == "/entrar/"
                and not request.META.get("HTTP_COOKIE")
            )
            if not health:
                response = HttpResponse(
                    "Recuperação ou manutenção em curso. Aguarde a confirmação do assistente.",
                    status=503,
                    content_type="text/plain; charset=utf-8",
                )
                response["Cache-Control"] = "no-store"
                response["Retry-After"] = "30"
                return response
        return self.get_response(request)
