import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.http import require_GET

PUBLIC_FILES = ["css/app.css", "js/pwa.js", "icons/icon-192.png", "icons/icon-512.png"]


@login_required
@require_GET
def connection_status(request):
    """Network presence alone does not prove that the PC/database is available."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return HttpResponse(status=204)


@require_GET
def manifest(request):
    return JsonResponse(
        {
            "id": "/",
            "name": "Gestão de Garrafas",
            "short_name": "Garrafas",
            "lang": "pt-PT",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#f4f7f5",
            "theme_color": "#126650",
            "description": "Gestão de stock de garrafas; operações requerem ligação.",
            "icons": [
                {
                    "src": static(f"icons/icon-{size}.png"),
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
    digest = hashlib.sha256(
        source.encode() + b"".join((root / name).read_bytes() for name in PUBLIC_FILES)
    ).hexdigest()[:16]
    # Resolve manifest-hashed production assets too; offline HTML uses those URLs.
    assets = ["/offline/", *(static(name) for name in PUBLIC_FILES)]
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
