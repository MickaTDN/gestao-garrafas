from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, F, Prefetch, Q, Sum
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from accounts.permissions import capabilities, require_access, require_operation, visible_movements
from inventory.models import Document, Movement, Reference
from inventory.reporting import can_regenerate, issued_filter, with_file_status

from .forms import HistoryFilterForm
from .operation_forms import OperationSearchForm


def administrator_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        require_access(request.user, "admin")
        return view(request, *args, **kwargs)

    return login_required(wrapped)


def operation_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        require_operation(request.user)
        return view(request, *args, **kwargs)

    return login_required(wrapped)


def permission_required(capability):
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            require_access(request.user, capability)
            return view(request, *args, **kwargs)

        return login_required(wrapped)

    return decorate


def _page(request, queryset, size=40):
    params = request.GET.copy()
    params.pop("page", None)
    return {
        "page_obj": Paginator(queryset, size).get_page(request.GET.get("page")),
        "query_string": params.urlencode(),
    }


@login_required
@require_GET
def home(request):
    allowed = capabilities(request.user)
    if not allowed:
        raise PermissionDenied("O seu perfil não tem acesso à aplicação.")
    references = (
        Reference.objects.filter(active=True)
        if "stock_view" in allowed
        else Reference.objects.none()
    )
    totals = references.aggregate(total_stock=Sum("current_stock"), reference_count=Count("pk"))
    alerts = references.filter(minimum__isnull=False, current_stock__lte=F("minimum"))
    return render(
        request,
        "web/home.html",
        {
            "section": "home",
            "total_stock": totals["total_stock"] or 0,
            "reference_count": totals["reference_count"],
            "alert_count": alerts.count(),
            "alerts": alerts.order_by("name")[:5],
        },
    )


@login_required
@require_GET
def stock(request):
    require_access(request.user, "stock_view")
    form = OperationSearchForm(request.GET)
    inactive = request.GET.get("state") == "inactive"
    if inactive:
        require_access(request.user, "catalog_manage")
    references = (
        Reference.objects.filter(active=not inactive)
        .select_related("location", "sector")
        .order_by("name", "pk")
    )
    valid = form.is_valid()
    if valid and form.cleaned_data["q"]:
        references = references.filter(name__icontains=form.cleaned_data["q"])
    elif not valid:
        references = references.none()
    return render(
        request,
        "web/stock_results.html" if request.GET.get("partial") == "stock" else "web/stock.html",
        {
            "section": "stock",
            "form": form,
            "inactive": inactive,
            **_page(request, references),
        },
        status=200 if valid else 400,
    )


@login_required
@require_GET
def reference_detail(request, pk):
    require_access(request.user, "stock_view")
    reference = get_object_or_404(
        Reference.objects.select_related("location", "sector").prefetch_related("opening_balances"),
        pk=pk,
    )
    return render(
        request, "web/reference_detail.html", {"section": "stock", "reference": reference}
    )


@login_required
@require_GET
def history(request):
    form = HistoryFilterForm(request.GET)
    movements = (
        Movement.objects.filter(status="confirmed")
        .select_related("person", "created_by", "confirmed_by", "correction_of")
        .prefetch_related(
            "lines__sources",
            Prefetch(
                "documents",
                queryset=with_file_status(Document.objects.filter(issued_filter(), kind="pdf")),
            ),
            "report_number",
            "location_changes__location_before",
            "location_changes__location_after",
            "location_changes__sector_before",
            "location_changes__sector_after",
        )
        .order_by("-date", "-pk")
    )
    if not (capabilities(request.user) & {"history_all", "entry", "exit", "inventory"}):
        raise PermissionDenied("O seu perfil não permite consultar movimentos.")
    movements = visible_movements(request.user, movements)
    valid = form.is_valid()
    if valid:
        query = form.cleaned_data
        if query["q"]:
            movements = movements.filter(
                Q(person_name__icontains=query["q"])
                | Q(person__name__icontains=query["q"])
                | Q(original_label__icontains=query["q"])
                | Q(document_number__icontains=query["q"])
                | Q(documents__metadata__report_number__icontains=query["q"])
                | Q(lines__reference_name__icontains=query["q"])
                | Q(lines__reference__code__icontains=query["q"])
            ).distinct()
        if query["start"]:
            movements = movements.filter(date__gte=query["start"])
        if query["end"]:
            movements = movements.filter(date__lte=query["end"])
    else:
        movements = movements.none()
    page_data = _page(request, movements, size=20)
    for movement in page_data["page_obj"]:
        for document in movement.documents.all():
            document.allow_regenerate = can_regenerate(request.user, document)
    return render(
        request,
        "web/history.html",
        {
            "section": "history",
            "form": form,
            **page_data,
        },
        status=200 if valid else 400,
    )


@administrator_required
@require_GET
def settings(request):
    return render(request, "web/settings.html", {"section": "settings"})


FEATURES = {
    "entry": (
        "Entradas",
        "Rascunhos persistentes, várias referências, pessoas pesquisáveis e relatório opcional.",
    ),
    "exit": (
        "Saídas",
        "Conferência das quantidades, validação simples ou assinatura e relatório obrigatório.",
    ),
    "inventory": (
        "Inventário físico",
        "Contagem em caixas e garrafas, motivo de ajuste e histórico de localização e setor.",
    ),
    "references": (
        "Referências",
        "Criação, edição e desativação com histórico preservado, capacidade de caixa e alertas opcionais.",
    ),
}


@administrator_required
@require_GET
def planned_feature(request, section):
    title, description = FEATURES[section]
    return render(
        request,
        "web/planned.html",
        {"section": section, "title": title, "description": description},
    )
