import json

from django import forms
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from web.views import permission_required

from .exports import export_snapshot


class StockExportForm(forms.Form):
    days = forms.TypedChoiceField(
        label="Entradas confirmadas incluídas",
        coerce=int,
        initial=180,
        choices=[
            (180, "Últimos 180 dias"),
            (90, "Últimos 90 dias"),
            (30, "Últimos 30 dias"),
            (1, "Último dia"),
        ],
    )


@permission_required("export")
@require_http_methods(["GET", "POST"])
def export(request):
    error = ""
    form = StockExportForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            data = export_snapshot(actor=request.user, days=form.cleaned_data["days"])
        except ValidationError as exception:
            error = " ".join(exception.messages)
        else:
            response = HttpResponse(
                json.dumps(data, ensure_ascii=False), content_type="application/json"
            )
            response["Content-Disposition"] = (
                'attachment; filename="stock-vertente-aveludada.vastock.json"'
            )
            return response
    return render(
        request,
        "web/vertente_export.html",
        {"section": "export", "form": form, "error": error},
        status=503 if error else 400 if form.is_bound and not form.is_valid() else 200,
    )
