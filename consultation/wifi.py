"""Sessionless, isolated machine endpoint. Never mounted in the management URLconf."""

import uuid

from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .sheets import MAX_BYTES
from .transport import DevicePrincipal, accept_upload


@csrf_exempt  # Device mTLS + signed/ciphered envelope + exact Origin; never cookie auth.
@require_http_methods(["OPTIONS", "POST"])
def receive(request):
    principal = getattr(request, "sheet_principal", None)
    if not isinstance(principal, DevicePrincipal):
        return HttpResponse(status=403)
    if request.method == "OPTIONS":
        if request.headers.get("Access-Control-Request-Method") != "POST":
            return HttpResponse(status=403)
        headers = {
            h.strip().lower()
            for h in request.headers.get("Access-Control-Request-Headers", "").split(",")
            if h.strip()
        }
        if not headers.issubset({"content-type", "x-gva-request"}):
            return HttpResponse(status=403)
        response = HttpResponse(status=204)
        response["Access-Control-Allow-Methods"] = "POST"
        response["Access-Control-Allow-Headers"] = "Content-Type, X-GVA-Request"
        return response
    if request.content_type != "application/json":
        return HttpResponse(status=415)
    try:
        size = int(request.META.get("CONTENT_LENGTH", "0"))
        if not 0 < size <= MAX_BYTES:
            return HttpResponse(status=413)
        request_id = request.headers.get("X-GVA-Request", "")
        if str(uuid.UUID(request_id)) != request_id:
            raise ValueError
        result = accept_upload(request.body, principal=principal, request_id=request_id)
    except (ValueError, ValidationError):
        return JsonResponse(
            {"error": "Folha ou autorização inválida. Não existe confirmação de receção."},
            status=400,
        )
    except Exception:
        return JsonResponse(
            {"error": "Receção não comprovada; conserve a folha e tente novamente."}, status=503
        )
    return JsonResponse(result, status=200)
