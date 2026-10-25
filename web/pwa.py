import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.http import require_GET

from .branding import APP_NAME, LOGO, icon_asset, original_asset


def public_files():
    return [
        "css/app.css",
        "js/pwa.js",
        *(icon_asset(size) for size in (192, 512)),
        *([LOGO] if original_asset(LOGO) else []),
    ]


@require_GET
def manifest(request):
    return JsonResponse(
        {
            "id": "/",
            "name": APP_NAME,
            "short_name": "Gestão Vertente",
            "lang": "pt-PT",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#f4f7f5",
            "theme_color": "#126650",
            "description": "Gestão de stock de garrafas; operações requerem ligação.",
            "icons": [
                {
                    "src": static(icon_asset(size)),
                    "sizes": f"{size}x{size}",
                    "type": "image/png",
                    "purpose": "any maskable",
                }
                for size in (192, 512)
            ],
        },
        content_type="application/manifest+json",
    )


@require_GET
def service_worker(request):
    root = Path(settings.BASE_DIR) / "static"
    source = (root / "js/service-worker.js").read_text()
    files = public_files()
    digest = hashlib.sha256(
        source.encode() + b"".join((root / name).read_bytes() for name in files)
    ).hexdigest()[:16]
    # Resolve manifest-hashed production assets too; offline HTML uses those URLs.
    assets = ["/offline/", *(static(name) for name in files)]
    source = "\n".join(
        f"const CACHE = 'gg-public-{digest}';"
        if line.startswith("const CACHE =")
        else f"const PUBLIC = new Set({json.dumps(assets)});"
        if line.startswith("const PUBLIC =")
        else line
        for line in source.splitlines()
    )
    response = HttpResponse(source, content_type="application/javascript")
    response["Cache-Control"] = "no-cache"
    response["Service-Worker-Allowed"] = "/"
    return response


@require_GET
def offline(request):
    return render(request, "web/offline.html")
