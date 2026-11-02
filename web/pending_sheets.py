from django import forms
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from consultation.models import AuthorizedDevice, PendingSheet, SheetReceipt
from consultation.sheets import MAX_BYTES, receive_sheet, reference_warnings, revoke_device

from .views import administrator_required


class Upload(forms.Form):
    file = forms.FileField(label="Ficheiro de folha cifrada")


@administrator_required
@require_http_methods(["GET", "POST"])
def inbox(request):
    form = Upload(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["file"]
        if upload.size > MAX_BYTES:
            form.add_error("file", "Ficheiro demasiado grande.")
        else:
            try:
                receipt = receive_sheet(upload.read(MAX_BYTES + 1), actor=request.user)
                return redirect("web:sheet-receipt", pk=receipt.pk)
            except ValidationError as error:
                form.add_error("file", error)
    return render(
        request,
        "web/pending_sheets.html",
        {
            "form": form,
            "sheets": PendingSheet.objects.order_by("-received_at")[:100],
            "devices": AuthorizedDevice.objects.filter(sheets_allowed=True),
        },
        status=400 if request.method == "POST" else 200,
    )


@administrator_required
@require_http_methods(["GET"])
def detail(request, pk):
    receipt = get_object_or_404(SheetReceipt, pk=pk)
    return render(
        request,
        "web/sheet_receipt.html",
        {"receipt": receipt, "warnings": reference_warnings(receipt.sheet)},
    )


@administrator_required
@require_http_methods(["GET"])
def original(request, pk):
    receipt = get_object_or_404(SheetReceipt, pk=pk)
    response = HttpResponse(bytes(receipt.original), content_type="application/octet-stream")
    response["Content-Disposition"] = f'attachment; filename="folha-{receipt.pk}.vasheet"'
    return response


@administrator_required
@require_http_methods(["POST"])
def revoke(request, pk):
    get_object_or_404(AuthorizedDevice, pk=pk)
    revoke_device(pk, actor=request.user)
    return redirect("web:sheets")
