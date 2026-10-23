"""Server-rendered operational screens. All writes delegate to domain services."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from inventory import catalog, operations
from inventory.models import Movement, Person, Reference
from inventory.services import confirm_movement, owned_draft, reference_state

from .catalog import _errors
from .catalog_forms import ReferenceForm
from .forms import StockFilterForm
from .operation_forms import HeaderForm, LineFormSet, ReviewForm, StartForm
from .views import _page, administrator_required


def _own(request, pk):
    movement = get_object_or_404(Movement, pk=pk, created_by=request.user, workflow_version=1)
    if movement.status != "draft":
        from django.http import Http404

        raise Http404
    owned_draft(movement, request.user)
    return movement


def _catalogue(request, *, active_only=True):
    form = StockFilterForm(request.GET)
    refs = Reference.objects.select_related("location", "sector").order_by("name", "pk")
    if active_only:
        refs = refs.filter(active=True)
    if form.is_valid():
        data = form.cleaned_data
        if data["q"]:
            refs = refs.filter(Q(name__icontains=data["q"]) | Q(code__icontains=data["q"]))
        if data["location"]:
            refs = refs.filter(location=data["location"])
        if data["sector"]:
            refs = refs.filter(sector=data["sector"])
    else:
        refs = refs.none()
    return form, refs


@administrator_required
@require_http_methods(["GET", "POST"])
def start(request, kind):
    form = StartForm(request.POST if request.method == "POST" else None)
    filter_form, refs = _catalogue(request)
    if kind != "inventory":
        form.fields.pop("inventory_scope")
    if request.method == "POST" and form.is_valid():
        try:
            scope = form.cleaned_data.get("inventory_scope") or "partial"
            if kind == "inventory" and scope == "full" and not filter_form.is_valid():
                raise ValidationError("Corrija os filtros do âmbito antes de criar o inventário.")
            movement = operations.create_draft(
                actor=request.user,
                kind=kind,
                inventory_scope=scope,
                references=refs if kind == "inventory" and scope == "full" else None,
            )
        except ValidationError as error:
            _errors(form, error)
        else:
            return redirect("web:operation-edit", pk=movement.pk)
    return render(
        request,
        "web/operations/start.html",
        {
            "section": kind,
            "kind": kind,
            "title": dict(Movement.Kind.choices)[kind],
            "form": form,
            "filter_form": filter_form,
        },
        status=400 if request.method == "POST" else 200,
    )


@administrator_required
@require_GET
def drafts(request):
    return render(
        request,
        "web/operations/drafts.html",
        {
            "section": "drafts",
            **_page(
                request,
                Movement.objects.filter(
                    created_by=request.user, status="draft", workflow_version=1
                ).prefetch_related("lines"),
            ),
        },
    )


def _initial(movement, lines):
    return [
        {
            "id": line.pk,
            "boxes": line.boxes,
            "units": line.units,
            "reason": line.reason,
            "target_location": line.target_location_id,
            "target_sector": line.target_sector_id,
            "basis_token": signing.dumps(
                {
                    "movement": movement.pk,
                    "revision": movement.revision,
                    "line": line.pk,
                    "state": reference_state(line.reference),
                },
                salt="count-basis",
            ),
        }
        for line in lines
    ]


@administrator_required
@require_http_methods(["GET", "POST"])
def edit(request, pk):
    try:
        movement = _own(request, pk)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
        return redirect("web:drafts")
    line_query = movement.lines.select_related(
        "reference__location", "reference__sector", "target_location", "target_sector"
    ).order_by("reference__code")
    if movement.kind == "inventory":
        _, filtered_refs = _catalogue(request, active_only=False)
        line_query = line_query.filter(reference__in=filtered_refs)
    lines_page = Paginator(line_query, 30).get_page(request.GET.get("page"))
    lines = list(lines_page.object_list)
    header = HeaderForm(
        request.POST if request.method == "POST" else None,
        initial={
            "revision": movement.revision,
            "date": movement.date,
            "person_name": movement.draft_person_name,
            "reason": movement.reason,
        },
    )
    if movement.kind == "inventory":
        header.fields.pop("person_name")
    formset = LineFormSet(
        request.POST if request.method == "POST" else None,
        initial=_initial(movement, lines),
        form_kwargs={"inventory": movement.kind == "inventory"},
    )
    filter_form, refs = _catalogue(request, active_only=movement.kind != "entry")
    refs = refs.exclude(pk__in=movement.lines.values_list("reference_id", flat=True))
    if movement.correction_of_id:
        refs = refs.filter(movement_lines__movement_id=movement.correction_of_id).distinct()
    refs_page = Paginator(refs, 20).get_page(request.GET.get("ref_page"))
    if request.method == "POST" and header.is_valid() and formset.is_valid():
        try:
            rows = []
            remove = []
            posted_ids = [form.cleaned_data["id"] for form in formset]
            if set(posted_ids) != {line.pk for line in lines} or len(posted_ids) != len(lines):
                raise ValidationError("O pedido deve conter exatamente as linhas desta página.")
            for form in formset:
                data = form.cleaned_data.copy()
                basis = data.pop("basis_token")
                if (basis["movement"], basis["revision"], basis["line"]) != (
                    movement.pk,
                    header.cleaned_data["revision"],
                    data["id"],
                ):
                    raise ValidationError("Conferência inválida para esta linha.")
                data["basis"] = basis["state"]
                if data.pop("remove"):
                    remove.append(data["id"])
                rows.append(data)
            add_ids = [int(value) for value in request.POST.getlist("add_reference")]
            # Do not accept forged selections outside the displayed search page.
            if not set(add_ids).issubset({ref.pk for ref in refs_page}):
                raise ValidationError("Seleção fora dos resultados apresentados.")
            action = request.POST.get("action", "save")
            reactivate_id = None
            if action.startswith("reactivate:"):
                reactivate_id = int(action.split(":", 1)[1])
                if movement.kind != "entry" or not any(
                    ref.pk == reactivate_id and not ref.active for ref in refs_page
                ):
                    raise ValidationError("Reativação inválida.")
                action = "reactivate"
            if action not in ("save", "review", "new-reference", "recheck", "reactivate"):
                raise ValidationError("Ação inválida.")
            if action == "new-reference" and movement.kind != "entry":
                raise ValidationError("Só pode criar referências numa entrada.")
            movement = operations.save_draft(
                pk,
                actor=request.user,
                revision=header.cleaned_data["revision"],
                header=header.cleaned_data,
                rows=rows,
                add_ids=add_ids,
                remove_ids=remove,
                recheck=action == "recheck",
            )
            if action == "reactivate":
                return redirect("web:operation-reactivate", pk=pk, reference_pk=reactivate_id)
            if action == "new-reference":
                return redirect("web:operation-reference", pk=pk)
            if action == "review":
                # Review is a separate POST, so refreshing its GET never accepts new stock silently.
                operations.review_draft(pk, actor=request.user, revision=movement.revision)
                return redirect("web:operation-review", pk=pk)
            messages.success(request, "Rascunho guardado. O stock permanece inalterado.")
            return redirect(request.get_full_path())
        except (ValidationError, ValueError) as error:
            _errors(
                header,
                error
                if isinstance(error, ValidationError)
                else ValidationError("Seleção inválida."),
            )
            # Save may have succeeded before review failed; force reopening to refresh revision.
            movement.refresh_from_db()
            if movement.revision != header.cleaned_data["revision"]:
                messages.error(request, " ".join(error.messages))
                return redirect(request.get_full_path())
    pairs = list(zip(lines, formset, strict=False))
    params = request.GET.copy()
    params.pop("page", None)
    ref_params = request.GET.copy()
    ref_params.pop("ref_page", None)
    return render(
        request,
        "web/operations/edit.html",
        {
            "section": movement.kind,
            "movement": movement,
            "header": header,
            "formset": formset,
            "pairs": pairs,
            "lines_page": lines_page,
            "line_params": params.urlencode(),
            "ref_params": ref_params.urlencode(),
            "refs_page": refs_page,
            "filter_form": filter_form,
            "people": Person.objects.filter(active=True).order_by("name"),
            "counted": movement.lines.filter(counted_quantity__isnull=False).count(),
            "total_lines": movement.lines.count(),
        },
        status=400 if request.method == "POST" else 200,
    )


@administrator_required
@require_http_methods(["GET", "POST"])
def review(request, pk):
    try:
        movement = _own(request, pk)
    except ValidationError:
        return redirect("web:drafts")
    if not movement.review_token:
        messages.error(request, "Guarde e reveja o rascunho antes de confirmar.")
        return redirect("web:operation-edit", pk=pk)
    form = ReviewForm(
        request.POST if request.method == "POST" else None, initial={"token": movement.review_token}
    )
    if movement.kind != "entry":
        form.fields.pop("report_requested")
    if request.method == "POST" and form.is_valid():
        try:
            confirm_movement(
                pk,
                actor=request.user,
                review_token=form.cleaned_data["token"],
                report_requested=form.cleaned_data.get("report_requested"),
            )
        except ValidationError as error:
            _errors(form, error)
        else:
            messages.success(
                request,
                "Operação confirmada. Dados para o relatório guardados; o PDF será disponibilizado na Etapa 4.",
            )
            return redirect("web:operation-detail", pk=pk)
    # Show exactly what was reviewed, not silently refreshed quantities.
    plans = []
    for line in movement.lines.select_related(
        "reference", "target_location", "target_sector"
    ).order_by("reference__code"):
        snapshot = movement.review_snapshot.get(str(line.reference_id), {})
        before = snapshot.get("stock", 0)
        quantity = line.counted_quantity - before if movement.kind == "inventory" else line.quantity
        plans.append(
            {"line": line, "before": before, "quantity": quantity, "after": before + quantity}
        )
    return render(
        request,
        "web/operations/review.html",
        {"section": movement.kind, "movement": movement, "form": form, "plans": plans},
        status=400 if request.method == "POST" else 200,
    )


@administrator_required
@require_http_methods(["GET", "POST"])
def cancel(request, pk):
    try:
        movement = _own(request, pk)
    except ValidationError:
        return redirect("web:drafts")
    error = None
    if request.method == "POST":
        try:
            if request.POST.get("confirm") != "yes":
                raise ValidationError("Confirme o cancelamento.")
            operations.cancel_draft(
                pk, actor=request.user, revision=int(request.POST.get("revision", "-1"))
            )
        except (ValidationError, ValueError) as exc:
            error = (
                " ".join(exc.messages) if isinstance(exc, ValidationError) else "Revisão inválida."
            )
        else:
            messages.success(
                request, "Rascunho cancelado sem alterar stock. Dados e auditoria preservados."
            )
            return redirect("web:drafts")
    return render(
        request,
        "web/operations/cancel.html",
        {"section": "drafts", "movement": movement, "error": error},
        status=400 if error else 200,
    )


@administrator_required
@require_http_methods(["GET", "POST"])
def new_reference(request, pk):
    movement = _own(request, pk)
    if movement.kind != "entry":
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied
    form = ReferenceForm(request.POST if request.method == "POST" else None)
    matches = (
        catalog.matching_references(request.POST.get("name", ""))
        if request.method == "POST"
        else []
    )
    if request.method == "POST" and form.is_valid():
        try:
            catalog.save_reference(actor=request.user, data=form.cleaned_data)
        except ValidationError as error:
            _errors(form, error)
            if isinstance(error, catalog.DuplicateReferenceError):
                matches = error.matches
        else:
            messages.success(
                request,
                "Referência criada. Pesquise-a e adicione-a à entrada; o rascunho foi preservado.",
            )
            return redirect("web:operation-edit", pk=pk)
    return render(
        request,
        "web/operations/reference.html",
        {"section": "entry", "movement": movement, "form": form, "matches": matches},
        status=400 if request.method == "POST" else 200,
    )


@administrator_required
@require_http_methods(["GET", "POST"])
def correction(request, pk):
    original = get_object_or_404(Movement, pk=pk, status="confirmed")
    form = StartForm(request.POST if request.method == "POST" else None)
    form.fields.pop("inventory_scope")
    form.fields["reason"].required = True
    if request.method == "POST" and form.is_valid():
        try:
            movement = operations.create_draft(
                actor=request.user,
                kind="inventory",
                correction_of=original,
                reason=form.cleaned_data["reason"],
                references=Reference.objects.filter(movement_lines__movement=original, active=True),
            )
        except ValidationError as error:
            _errors(form, error)
        else:
            return redirect("web:operation-edit", pk=movement.pk)
    return render(
        request,
        "web/operations/start.html",
        {"section": "inventory", "title": f"Correção de {original}", "form": form},
    )


# Confirmed details are visible to both authenticated profiles.


@login_required
@require_GET
def detail(request, pk):
    movement = get_object_or_404(
        Movement.objects.select_related(
            "person", "created_by", "confirmed_by", "correction_of"
        ).prefetch_related(
            "lines__sources",
            "location_changes__location_before",
            "location_changes__location_after",
            "location_changes__sector_before",
            "location_changes__sector_after",
            "corrections",
            "audit_events__actor",
        ),
        pk=pk,
        status="confirmed",
    )
    return render(
        request, "web/operations/detail.html", {"section": "history", "movement": movement}
    )


@administrator_required
@require_http_methods(["GET", "POST"])
def reactivate(request, pk, reference_pk):
    movement = _own(request, pk)
    if movement.kind != "entry":
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied
    reference = get_object_or_404(Reference.objects.select_related("location"), pk=reference_pk)
    error = None
    if request.method == "POST":
        if request.POST.get("confirm") != "yes":
            error = "Confirme explicitamente a reativação da referência original."
        else:
            catalog.set_reference_active(actor=request.user, reference_id=reference_pk, active=True)
            messages.success(
                request,
                "Referência original reativada; código e histórico preservados. Adicione-a à entrada.",
            )
            return redirect("web:operation-edit", pk=pk)
    return render(
        request,
        "web/operations/reactivate.html",
        {"section": "entry", "movement": movement, "reference": reference, "error": error},
        status=400 if error else 200,
    )
