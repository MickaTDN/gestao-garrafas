import io

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from inventory.documents import DocumentIntegrityError, verified_bytes
from inventory.models import AuditEvent, Document

from .forms import HistoryFilterForm
from .views import _page


@login_required
@require_GET
def reports(request):
    from django.db.models import Q

    form = HistoryFilterForm(request.GET)
    documents = (
        Document.objects.filter(kind="pdf", payload__isnull=False, movement__status="confirmed")
        .defer("payload", "metadata")
        .select_related("movement")
        .order_by("-movement__date", "-pk")
    )
    if form.is_valid():
        data = form.cleaned_data
        if data["q"]:
            documents = documents.filter(
                Q(movement__person_name__icontains=data["q"])
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
    document = get_object_or_404(
        Document,
        pk=pk,
        payload__isnull=False,
        movement__status="confirmed",
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
    suffix = "pdf" if document.kind == "pdf" else "png"
    AuditEvent.objects.create(
        actor=request.user,
        action="document.opened",
        movement_id=document.movement_id,
        details={"document_id": document.pk, "download": request.GET.get("download") == "1"},
    )
    response = FileResponse(
        io.BytesIO(payload),
        content_type=document.content_type,
        filename=f"mov-{document.movement_id}-{document.kind}.{suffix}",
        as_attachment=request.GET.get("download") == "1",
    )
    return response
