from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from inventory import catalog as services
from inventory.models import Location, Reference, Sector

from .catalog_forms import (
    LocationForm,
    ReferenceForm,
    ReferenceMatchForm,
    ReferenceSearchForm,
    ReferenceStateForm,
    SectorForm,
)
from .views import _page, permission_required


def _errors(form, error):
    if hasattr(error, "message_dict"):
        for field, errors in error.message_dict.items():
            for message in errors:
                form.add_error(field if field in form.fields else None, message)
    else:
        for message in error.messages:
            form.add_error(None, message)


@permission_required("catalog_manage")
@require_GET
def reference_list(request):
    form = ReferenceSearchForm(request.GET)
    references = Reference.objects.select_related("location", "sector").order_by("code")
    if form.is_valid():
        if query := form.cleaned_data["q"]:
            references = references.filter(Q(name__icontains=query) | Q(code__icontains=query))
        state = form.cleaned_data["state"]
        if state:
            references = references.filter(active=state == "active")
    else:
        references = references.none()
    return render(
        request,
        "web/catalog/references.html",
        {
            "section": "stock",
            "form": form,
            **_page(request, references),
        },
    )


@permission_required("catalog_manage")
@require_http_methods(["GET", "POST"])
def reference_create(request):
    form = ReferenceForm(request.POST if request.method == "POST" else None)
    match_form = ReferenceMatchForm(
        request.GET if request.method == "GET" and "check_name" in request.GET else None
    )
    matches = []
    if request.method == "GET" and match_form.is_bound and match_form.is_valid():
        name = match_form.cleaned_data["check_name"]
        matches = services.matching_references(name)
        form = ReferenceForm(initial={"name": name})
    if request.method == "POST":
        # Show matches even if another field in the creation form is invalid.
        name_form = ReferenceMatchForm({"check_name": request.POST.get("name", "")})
        if name_form.is_valid():
            name = name_form.cleaned_data["check_name"]
            matches = services.matching_references(name)
            match_form = ReferenceMatchForm(initial={"check_name": name})
    if request.method == "POST" and form.is_valid():
        try:
            reference = services.save_reference(actor=request.user, data=form.cleaned_data)
        except ValidationError as error:
            _errors(form, error)
            if isinstance(error, services.DuplicateReferenceError):
                matches = error.matches
        else:
            messages.success(request, "Referência criada com stock inicial de zero garrafas.")
            return redirect("web:reference-detail", pk=reference.pk)
    return render(
        request,
        "web/catalog/form.html",
        {
            "section": "stock",
            "form": form,
            "title": "Nova referência",
            "description": "O código é atribuído automaticamente. O stock é alterado apenas pelos movimentos.",
            "back_url": "web:stock",
            "match_form": match_form,
            "matching_references": matches,
        },
        status=400 if request.method == "POST" else 200,
    )


@permission_required("catalog_manage")
@require_http_methods(["GET", "POST"])
def reference_edit(request, pk):
    reference = get_object_or_404(Reference, pk=pk)
    form = ReferenceForm(request.POST if request.method == "POST" else None, instance=reference)
    if request.method == "POST" and form.is_valid():
        try:
            reference = services.save_reference(
                actor=request.user, data=form.cleaned_data, reference_id=pk
            )
        except ValidationError as error:
            _errors(form, error)
        else:
            messages.success(request, "Ficha atualizada. O stock e o histórico foram conservados.")
            return redirect("web:reference-detail", pk=reference.pk)
    return render(
        request,
        "web/catalog/form.html",
        {
            "section": "stock",
            "form": form,
            "title": "Editar referência",
            "description": f"{reference.code} · {reference.current_stock} garrafas em stock",
            "back_url": "web:stock",
        },
        status=400 if request.method == "POST" else 200,
    )


@permission_required("catalog_manage")
@require_http_methods(["GET", "POST"])
def reference_toggle(request, pk):
    reference = get_object_or_404(Reference, pk=pk)
    form = ReferenceStateForm(
        request.POST if request.method == "POST" else None,
        initial={"active": "0" if reference.active else "1"},
    )
    if request.method == "POST" and form.is_valid():
        try:
            reference = services.set_reference_active(
                actor=request.user, reference_id=pk, active=form.cleaned_data["active"]
            )
        except ValidationError as error:
            _errors(form, error)
            reference.refresh_from_db()
        else:
            messages.success(
                request,
                "Referência ativada."
                if reference.active
                else "Referência desativada; histórico conservado.",
            )
            return redirect("web:reference-detail", pk=reference.pk)
    blocked = reference.active and reference.current_stock != 0
    return render(
        request,
        "web/catalog/confirm.html",
        {
            "section": "stock",
            "title": "Desativar referência" if reference.active else "Ativar referência",
            "description": reference.name,
            "form": form,
            "detail": "O stock, os movimentos e os dados da referência permanecem guardados.",
            "back_url": "web:stock",
            "blocked": blocked,
            "error": (
                "Não é possível desativar esta referência porque ainda existem garrafas em stock."
                if blocked and request.method == "GET"
                else None
            ),
        },
        status=400 if request.method == "POST" else 200,
    )


@permission_required("locations_manage")
@require_GET
def location_list(request):
    locations = Location.objects.annotate(
        reference_count=Count("references", distinct=True)
    ).prefetch_related(
        Prefetch(
            "sectors",
            queryset=Sector.objects.annotate(reference_count=Count("references")).order_by("pk"),
        )
    )
    return render(
        request, "web/catalog/locations.html", {"section": "settings", "locations": locations}
    )


def _save_simple(request, *, form_class, instance, title, save, id_key):
    form = form_class(request.POST if request.method == "POST" else None, instance=instance)
    if form_class is SectorForm and not instance and request.GET.get("location"):
        form.initial["location"] = request.GET["location"]
    if request.method == "POST" and form.is_valid():
        try:
            save(
                actor=request.user,
                data=form.cleaned_data,
                **{id_key: instance.pk if instance else None},
            )
        except ValidationError as error:
            _errors(form, error)
        else:
            messages.success(request, "Alteração guardada.")
            return redirect("web:locations")
    return render(
        request,
        "web/catalog/form.html",
        {
            "section": "settings",
            "title": title,
            "form": form,
            "back_url": "web:locations",
        },
        status=400 if request.method == "POST" else 200,
    )


@permission_required("locations_manage")
@require_http_methods(["GET", "POST"])
def location_create(request):
    return _save_simple(
        request,
        form_class=LocationForm,
        instance=None,
        title="Nova localização",
        save=services.save_location,
        id_key="location_id",
    )


@permission_required("locations_manage")
@require_http_methods(["GET", "POST"])
def location_edit(request, pk):
    return _save_simple(
        request,
        form_class=LocationForm,
        instance=get_object_or_404(Location, pk=pk),
        title="Editar localização",
        save=services.save_location,
        id_key="location_id",
    )


@permission_required("locations_manage")
@require_http_methods(["GET", "POST"])
def sector_create(request):
    return _save_simple(
        request,
        form_class=SectorForm,
        instance=None,
        title="Novo setor",
        save=services.save_sector,
        id_key="sector_id",
    )


@permission_required("locations_manage")
@require_http_methods(["GET", "POST"])
def sector_edit(request, pk):
    return _save_simple(
        request,
        form_class=SectorForm,
        instance=get_object_or_404(Sector, pk=pk),
        title="Editar setor",
        save=services.save_sector,
        id_key="sector_id",
    )


def _delete(request, *, instance, service, id_key, title):
    error = None
    if request.method == "POST":
        try:
            service(actor=request.user, **{id_key: instance.pk})
        except ValidationError as exc:
            error = " ".join(exc.messages)
        else:
            messages.success(request, "Remoção concluída.")
            return redirect("web:locations")
    return render(
        request,
        "web/catalog/confirm.html",
        {
            "section": "settings",
            "title": title,
            "description": str(instance),
            "detail": "A remoção só é permitida quando não existem referências ou histórico associados.",
            "error": error,
            "back_url": "web:locations",
        },
        status=400 if error else 200,
    )


@permission_required("locations_manage")
@require_http_methods(["GET", "POST"])
def location_delete(request, pk):
    return _delete(
        request,
        instance=get_object_or_404(Location, pk=pk),
        service=services.delete_location,
        id_key="location_id",
        title="Remover localização",
    )


@permission_required("locations_manage")
@require_http_methods(["GET", "POST"])
def sector_delete(request, pk):
    return _delete(
        request,
        instance=get_object_or_404(Sector, pk=pk),
        service=services.delete_sector,
        id_key="sector_id",
        title="Remover setor",
    )
