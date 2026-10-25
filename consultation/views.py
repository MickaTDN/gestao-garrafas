import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from .exports import export_snapshot


@login_required
@require_http_methods(["GET", "POST"])
def export(request):
    error = ""
    if request.method == "POST":
        try:
            data = export_snapshot(actor=request.user)
        except ValidationError as exception:
            error = " ".join(exception.messages)
        else:
            response = HttpResponse(
                json.dumps(data, ensure_ascii=False), content_type="application/json"
            )
            response["Content-Disposition"] = 'attachment; filename="vertente-stock.vastock.json"'
            return response
    return render(
        request,
        "web/vertente_export.html",
        {"section": "export", "error": error},
        status=503 if error else 200,
    )
