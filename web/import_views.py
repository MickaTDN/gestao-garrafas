from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from imports.reconciliation import publish_preview
from inventory.models import ImportBatch, ImportPreview
from web.views import administrator_required


class PublicationForm(forms.Form):
    confirmation_token = forms.UUIDField(widget=forms.HiddenInput)
    total = forms.IntegerField(min_value=0, label="Total de garrafas da pré-visualização")
    confirm = forms.BooleanField(label="Confirmo a publicação definitiva deste lote revisto.")


@never_cache
@administrator_required
@require_GET
def import_list(request):
    batches = ImportBatch.objects.prefetch_related("previews").order_by("-created_at")
    return render(request, "web/imports/list.html", {
        "section": "settings", "page_obj": Paginator(batches, 20).get_page(request.GET.get("page")),
    })


def preview_context(request, preview, form=None):
    return {
        "section": "settings", "preview": preview,
        "page_obj": Paginator(preview.rows, 40).get_page(request.GET.get("page")),
        "form": form if form is not None else PublicationForm(initial={
            "confirmation_token": preview.confirmation_token,
        }),
    }


@never_cache
@administrator_required
@require_GET
def import_preview(request, pk):
    preview = get_object_or_404(ImportPreview.objects.select_related("import_batch"), pk=pk)
    return render(request, "web/imports/preview.html", preview_context(request, preview))


@never_cache
@administrator_required
@require_GET
def import_report(request, pk):
    preview = get_object_or_404(ImportPreview, pk=pk)
    data = {
        "preview_id": str(preview.pk), "published": bool(preview.published_at),
        "summary": preview.summary, "rows": preview.rows,
        "decisions": preview.decisions, "validation_report": preview.validation_report,
    }
    response = JsonResponse(data, json_dumps_params={"ensure_ascii": False, "indent": 2})
    response["Content-Disposition"] = f'attachment; filename="reconciliation-{preview.pk}.json"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


@never_cache
@administrator_required
@require_POST
def import_publish(request, pk):
    preview = get_object_or_404(ImportPreview.objects.select_related("import_batch"), pk=pk)
    form = PublicationForm(request.POST)
    if form.is_valid():
        if form.cleaned_data["total"] != preview.summary.get("total_stock"):
            form.add_error("total", "O total deve corresponder exatamente à pré-visualização.")
        else:
            try:
                publish_preview(preview.pk, actor=request.user,
                                confirmation_token=form.cleaned_data["confirmation_token"])
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, "Lote publicado e reconciliação validada.")
                return redirect("web:import-preview", pk=preview.pk)
    return render(request, "web/imports/preview.html",
                  preview_context(request, preview, form), status=400)
