"""Optional, original brand assets. Missing artwork is never redrawn or substituted."""

from pathlib import Path

from django.conf import settings

APP_NAME = "Gestão Vertente Aveludada"
LOGO = "branding/copo-com-vida-logo.png"


def original_asset(name):
    path = Path(settings.BASE_DIR) / "static" / name
    return path if path.is_file() else None


def icon_asset(size):
    name = f"branding/copo-com-vida-{size}.png"
    # Keep the previously shipped technical icon until original artwork is supplied.
    return name if original_asset(name) else f"icons/icon-{size}.png"


def branding(request):
    return {
        "app_name": APP_NAME,
        "brand_logo": LOGO if original_asset(LOGO) else None,
        "brand_icon": icon_asset(192),
    }
