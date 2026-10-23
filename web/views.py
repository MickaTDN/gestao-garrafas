from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, F, Q, Sum
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from inventory.models import Location, Movement, Reference

from .forms import HistoryFilterForm, StockFilterForm


def administrator_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_administrator:
            raise PermissionDenied("Esta área está reservada ao administrador.")
        return view(request, *args, **kwargs)

    return login_required(wrapped)


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
    references = Reference.objects.filter(active=True)
    totals = references.aggregate(total_stock=Sum("current_stock"), reference_count=Count("pk"))
    alerts = references.filter(minimum__isnull=False, current_stock__lte=F("minimum"))
    locations = [
        {"name": location.name, "reference_count": references.filter(location=location).count()}
        for location in Location.objects.filter(active=True).order_by("pk")
    ]
    return render(request, "web/home.html", {
        "section": "home",
        "total_stock": totals["total_stock"] or 0,
        "reference_count": totals["reference_count"],
        "alert_count": alerts.count(),
        "alerts": alerts.order_by("name")[:5],
        "draft_count": Movement.objects.filter(status="draft").count(),
        "locations": locations,
    })


@login_required
@require_GET
def stock(request):
    form = StockFilterForm(request.GET)
    references = Reference.objects.filter(active=True).select_related("location", "sector").order_by("name", "pk")
    valid = form.is_valid()
    if valid:
        query = form.cleaned_data
        if query["q"]:
            references = references.filter(Q(name__icontains=query["q"]) | Q(code__icontains=query["q"]))
        if query["location"]:
            references = references.filter(location=query["location"])
        if query["sector"]:
            references = references.filter(sector=query["sector"])
    else:
        references = references.none()
    return render(request, "web/stock.html", {
        "section": "stock",
        "form": form,
        **_page(request, references),
    }, status=200 if valid else 400)


@login_required
@require_GET
def reference_detail(request, pk):
    reference = get_object_or_404(
        Reference.objects.select_related("location", "sector").prefetch_related("opening_balances"),
        pk=pk,
    )
    return render(request, "web/reference_detail.html", {"section": "stock", "reference": reference})


@login_required
@require_GET
def history(request):
    form = HistoryFilterForm(request.GET)
    movements = Movement.objects.filter(status="confirmed").select_related("person").prefetch_related("lines__sources").order_by("-date", "-pk")
    valid = form.is_valid()
    if valid:
        query = form.cleaned_data
        if query["q"]:
            movements = movements.filter(
                Q(person__name__icontains=query["q"])
                | Q(original_label__icontains=query["q"])
                | Q(document_number__icontains=query["q"])
                | Q(lines__reference_name__icontains=query["q"])
                | Q(lines__reference__code__icontains=query["q"])
            ).distinct()
        if query["start"]:
            movements = movements.filter(date__gte=query["start"])
        if query["end"]:
            movements = movements.filter(date__lte=query["end"])
    else:
        movements = movements.none()
    return render(request, "web/history.html", {
        "section": "history", "form": form, **_page(request, movements, size=20),
    }, status=200 if valid else 400)


@administrator_required
@require_GET
def settings(request):
    return render(request, "web/settings.html", {"section": "settings"})


FEATURES = {
    "entry": ("Entradas", "Rascunhos persistentes, várias referências, pessoas pesquisáveis e relatório opcional."),
    "exit": ("Saídas", "Conferência das quantidades, validação simples ou assinatura e relatório obrigatório."),
    "inventory": ("Inventário físico", "Contagem em caixas e garrafas, motivo de ajuste e histórico de localização e setor."),
    "references": ("Referências", "Criação, edição e desativação com histórico preservado, capacidade de caixa e alertas opcionais."),
}


@administrator_required
@require_GET
def planned_feature(request, section):
    title, description = FEATURES[section]
    return render(request, "web/planned.html", {"section": section, "title": title, "description": description})
