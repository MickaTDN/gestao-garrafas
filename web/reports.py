import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.permissions import require_access, visible_movements
from inventory.documents import DocumentIntegrityError, verified_bytes
from inventory.models import AuditEvent, Document, Movement
from inventory.reporting import (
    authorized_document,
    available_filter,
    delete_pdf,
    regenerate_pdf,
    reproduce,
)

from .forms import HistoryFilterForm
from .views import _page


@login_required
@require_GET
def reports(request):
    from django.db.models import Q

    require_access(request.user, "reports_view")
    form = HistoryFilterForm(request.GET)
    movements = visible_movements(request.user, Movement.objects.filter(status="confirmed"))
    documents = (
        Document.objects.filter(available_filter(), kind="pdf", movement__in=movements)
        .defer("payload")
        .select_related("movement")
        .order_by("-movement__date", "-pk")
    )
    if form.is_valid():
        data = form.cleaned_data
        if data["q"]:
            documents = documents.filter(
                Q(metadata__report_number__icontains=data["q"])
                | Q(movement__person_name__icontains=data["q"])
                | Q(movement__lines__reference_name__icontains=data["q"])
                | Q(movement__lines__reference__code__icontains=data["q"])
            ).distinct()
        if data["start"]:
            documents = documents.filter(movement__date__gte=data["start"])
        if data["end"]:
            documents = documents.filter(movement__date__lte=data["end"])
    else:
        documents = documents.none()
    return render(
        request,
        "web/reports.html",
        {"section": "reports", "form": form, **_page(request, documents)},
        status=200 if form.is_valid() else 400,
    )


@login_required
@require_GET
def content(request, pk):
    require_access(request.user, "reports_view")
    movements = visible_movements(request.user, Movement.objects.filter(status="confirmed"))
    document = get_object_or_404(
        Document.objects.filter(available_filter()),
        pk=pk,
        movement__in=movements,
        kind__in=["pdf", "signature"],
    )
    try:
        payload = verified_bytes(document)
    except DocumentIntegrityError:
        AuditEvent.objects.create(
            actor=request.user,
            action="document.integrity_failed",
            movement_id=document.movement_id,
            details={"document_id": document.pk},
        )
        return HttpResponse(
            "Documento indisponível: a verificação de integridade falhou.",
            status=503,
            content_type="text/plain; charset=utf-8",
        )
    AuditEvent.objects.create(
        actor=request.user,
        action="document.opened",
        movement_id=document.movement_id,
        details={"document_id": document.pk, "download": request.GET.get("download") == "1"},
    )
    suffix = "pdf" if document.kind == "pdf" else "png"
    return FileResponse(
        io.BytesIO(payload),
        content_type=document.content_type,
        filename=f"{document.number.replace('/', '-')}-{document.kind}.{suffix}",
        as_attachment=request.GET.get("download") == "1",
    )


@login_required
@require_http_methods(["GET", "POST"])
def delete(request, pk):
    require_access(request.user, "reports_manage")
    document = authorized_document(request.user, pk)
    error = None
    try:
        reproduce(document)
    except (ValidationError, DocumentIntegrityError) as exc:
        error = " ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
    if request.method == "POST":
        if request.POST.get("confirm") != "yes":
            error = "Confirme explicitamente a eliminação apenas do ficheiro PDF."
        elif not error:
            try:
                delete_pdf(actor=request.user, document_id=pk)
            except (ValidationError, DocumentIntegrityError) as exc:
                error = " ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
            else:
                messages.success(
                    request,
                    "Ficheiro PDF eliminado. Movimento, stock, número e evidências preservados. Pode regenerá-lo através do Histórico.",
                )
                return redirect("web:reports")
    return render(
        request,
        "web/report_delete.html",
        {"section": "reports", "document": document, "error": error},
        status=400 if request.method == "POST" and error else 200,
    )


@login_required
@require_POST
def regenerate(request, pk):
    try:
        document = regenerate_pdf(actor=request.user, document_id=pk)
    except (ValidationError, DocumentIntegrityError) as error:
        messages.error(
            request, " ".join(error.messages) if isinstance(error, ValidationError) else str(error)
        )
        document = authorized_document(request.user, pk)
    else:
        messages.success(
            request,
            "Reprodução verificada byte a byte do relatório original. Número, dados e assinatura preservados; operação auditada."
            if getattr(document, "file_was_regenerated", False)
            else "O PDF original já está disponível; não foi necessário regenerar.",
        )
    return redirect("web:operation-detail", pk=document.movement_id)
