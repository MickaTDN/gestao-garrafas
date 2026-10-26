"""Server-rendered operational screens. All writes delegate to domain services."""

from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods

from accounts.permissions import require_access, require_operation, visible_movements
from inventory import catalog, operations
from inventory.models import Movement, Person, Reference
from inventory.presentation import entered_quantity, stock_quantity
from inventory.reporting import can_regenerate, issued_filter, with_file_status
from inventory.services import confirm_movement, owned_draft, reference_state

from .catalog import _errors
from .catalog_forms import ReferenceForm
from .forms import StockFilterForm
from .operation_forms import HeaderForm, LineFormSet, OperationSearchForm, ReviewForm, StartForm
from .views import _page, operation_required, permission_required


def _own(request, pk):
    movement = get_object_or_404(Movement, pk=pk, created_by=request.user, workflow_version=1)
    if movement.status != "draft":
        from django.http import Http404

        raise Http404
    owned_draft(movement, request.user)
    return movement


def _expired(movement):
    return bool(
        movement.pk
        and (
            movement.date != timezone.localdate()
            or timezone.localtime(movement.created_at).date() != timezone.localdate()
        )
    )


def _catalogue(request, *, active_only=True, name_only=False):
    search = (
        {"q": request.POST.get("search_q", request.GET.get("q", ""))}
        if request.method == "POST"
        else request.GET
    )
    form = OperationSearchForm(search) if name_only else StockFilterForm(request.GET)
    refs = Reference.objects.select_related("location", "sector").order_by("name", "pk")
    if active_only:
        refs = refs.filter(active=True)
    if form.is_valid():
        data = form.cleaned_data
        if name_only and not data["q"]:
            refs = refs.none()
        if data["q"]:
            refs = (
                refs.filter(name__icontains=data["q"])
                if name_only
                else refs.filter(Q(name__icontains=data["q"]) | Q(code__icontains=data["q"]))
            )
        if data.get("location"):
            refs = refs.filter(location=data["location"])
        if data.get("sector"):
            refs = refs.filter(sector=data["sector"])
    else:
        refs = refs.none()
    return form, refs


def _pending(request, kind):
    return Paginator(
        Movement.objects.filter(
            created_by=request.user, status="draft", workflow_version=1, kind=kind
        ).order_by("-pk"),
        10,
    ).get_page(request.GET.get("pending_page"))


def _search_results(request, movement, refs_page, filter_form):
    params = request.GET.copy()
    for key in ("partial", "ref_page"):
        params.pop(key, None)
    return render(
        request,
        "web/operations/results.html",
        {
            "movement": movement,
            "refs_page": refs_page,
            "searched": bool(filter_form.is_valid() and filter_form.cleaned_data.get("q")),
            "ref_params": params.urlencode(),
        },
    )


def _new_movement(request, kind):
    """Render a complete, unsaved form on GET; persist only an explicit valid POST."""
    movement = Movement(kind=kind, created_by=request.user, workflow_version=1)
    header = HeaderForm(
        request.POST if request.method == "POST" else None,
        initial={"revision": 0, "date": movement.date, "person_name": "", "reason": ""},
    )
    header.fields["reason"].label = "Observações (opcional)"
    header.fields["person_name"].label = (
        "Pessoa que entregou" if kind == "entry" else "Pessoa que levantou"
    )
    scope_form = None
    if kind == "inventory":
        header.fields.pop("person_name")
        scope_form = StartForm(
            request.POST if request.method == "POST" else None,
            initial={
                "inventory_scope": "full"
                if request.GET.get("inventory_scope") == "full"
                else "partial"
            },
        )
        scope_form.fields.pop("reason")
        scope_form.fields["inventory_scope"].widget.attrs["form"] = "operation-form"
    formset = LineFormSet(request.POST if request.method == "POST" else None, initial=[])
    filter_form, refs = _catalogue(
        request, active_only=kind != "entry", name_only=kind != "inventory"
    )
    refs_page = Paginator(refs, 20).get_page(request.GET.get("ref_page"))
    if request.method == "GET" and request.GET.get("partial") == "references":
        return _search_results(request, movement, refs_page, filter_form)
    if (
        request.method == "POST"
        and header.is_valid()
        and formset.is_valid()
        and (scope_form is None or scope_form.is_valid())
    ):
        try:
            if header.cleaned_data["revision"] != 0 or len(formset) != 0:
                raise ValidationError("Selecione as referências antes de introduzir quantidades.")
            add_ids = [int(value) for value in request.POST.getlist("add_reference")]
            if request.POST.get("action", "").startswith("add:"):
                add_ids = [int(request.POST["action"].split(":", 1)[1])]
            if not set(add_ids).issubset({ref.pk for ref in refs_page}):
                raise ValidationError("Seleção fora dos resultados apresentados.")
            action = request.POST.get("action", "save")
            if action.startswith("add:"):
                action = "save"
            if action == "new-reference":
                require_access(request.user, "catalog_manage")
            reactivate_id = None
            if action.startswith("reactivate:"):
                reactivate_id = int(action.split(":", 1)[1])
                if kind != "entry" or not any(
                    ref.pk == reactivate_id and not ref.active for ref in refs_page
                ):
                    raise ValidationError("Reativação inválida.")
                require_access(request.user, "catalog_manage")
                action = "reactivate"
            if action not in ("save", "new-reference", "reactivate") or (
                action == "new-reference" and kind != "entry"
            ):
                raise ValidationError("Ação inválida.")
            scope = (
                (scope_form.cleaned_data.get("inventory_scope") or "partial")
                if scope_form
                else "partial"
            )
            if kind == "inventory" and scope == "full" and not filter_form.is_valid():
                raise ValidationError("Corrija os filtros do âmbito do inventário.")
            with transaction.atomic():
                saved = operations.create_draft(
                    actor=request.user,
                    kind=kind,
                    inventory_scope=scope,
                    references=refs if kind == "inventory" and scope == "full" else None,
                )
                operations.save_draft(
                    saved.pk,
                    actor=request.user,
                    revision=0,
                    header=header.cleaned_data,
                    add_ids=add_ids if scope != "full" else (),
                )
            if action == "new-reference":
                return redirect("web:operation-reference", pk=saved.pk)
            if action == "reactivate":
                return redirect("web:operation-reactivate", pk=saved.pk, reference_pk=reactivate_id)
            return redirect("web:operation-edit", pk=saved.pk)
        except (ValidationError, ValueError) as error:
            _errors(
                header,
                error
                if isinstance(error, ValidationError)
                else ValidationError("Seleção inválida."),
            )
    params = request.GET.copy()
    params.pop("ref_page", None)
    return render(
        request,
        "web/operations/edit.html",
        {
            "section": kind,
            "movement": movement,
            "header": header,
            "formset": formset,
            "pairs": [],
            "refs_page": refs_page,
            "ref_params": params.urlencode(),
            "filter_form": filter_form,
            "searched": bool(filter_form.is_valid() and filter_form.cleaned_data.get("q")),
            "people": Person.objects.filter(active=True).order_by("name"),
            "pending_page": _pending(request, kind),
            "scope_form": scope_form,
        },
        status=400 if request.method == "POST" else 200,
    )


@operation_required
@require_http_methods(["GET", "POST"])
def start(request, kind):
    require_operation(request.user, kind)
    return _new_movement(request, kind)


@operation_required
@require_GET
def drafts(request):
    require_operation(request.user)
    return render(
        request,
        "web/operations/drafts.html",
        {
            "section": "drafts",
            **_page(
                request,
                visible_movements(
                    request.user,
                    Movement.objects.filter(
                        created_by=request.user, status="draft", workflow_version=1
                    ),
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


@operation_required
@require_http_methods(["GET", "POST"])
def edit(request, pk):
    try:
        movement = _own(request, pk)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
        return redirect("web:drafts")
    line_query = movement.lines.select_related(
        "reference__location", "reference__sector", "target_location", "target_sector"
    ).order_by("reference__name", "pk")
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
    else:
        header.fields["person_name"].label = (
            "Pessoa que entregou" if movement.kind == "entry" else "Pessoa que levantou"
        )
    header.fields["reason"].label = (
        "Motivo da correção" if movement.correction_of_id else "Observações (opcional)"
    )
    formset = LineFormSet(
        request.POST if request.method == "POST" else None,
        initial=_initial(movement, lines),
        form_kwargs={"inventory": movement.kind == "inventory"},
    )
    filter_form, refs = _catalogue(
        request, active_only=movement.kind != "entry", name_only=movement.kind != "inventory"
    )
    refs = refs.exclude(pk__in=movement.lines.values_list("reference_id", flat=True))
    if movement.correction_of_id:
        refs = refs.filter(movement_lines__movement_id=movement.correction_of_id).distinct()
    refs_page = Paginator(refs, 20).get_page(request.GET.get("ref_page"))
    if request.method == "GET" and request.GET.get("partial") == "references":
        return _search_results(request, movement, refs_page, filter_form)
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
            check_ids = []
            if action.startswith("add:"):
                add_ids = [int(action.split(":", 1)[1])]
                if not set(add_ids).issubset({ref.pk for ref in refs_page}):
                    raise ValidationError("Seleção fora dos resultados apresentados.")
                action = "save"
            if action.startswith("check:"):
                check_ids = [int(action.split(":", 1)[1])]
                action = "save"
            if action.startswith("remove:"):
                remove.append(int(action.split(":", 1)[1]))
                action = "save"
            if action == "new-reference":
                require_access(request.user, "catalog_manage")
            reactivate_id = None
            if action.startswith("reactivate:"):
                reactivate_id = int(action.split(":", 1)[1])
                if movement.kind != "entry" or not any(
                    ref.pk == reactivate_id and not ref.active for ref in refs_page
                ):
                    raise ValidationError("Reativação inválida.")
                require_access(request.user, "catalog_manage")
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
                check_ids=check_ids,
            )
            if action == "reactivate":
                return redirect("web:operation-reactivate", pk=pk, reference_pk=reactivate_id)
            if action == "new-reference":
                return redirect("web:operation-reference", pk=pk)
            if action == "review":
                # Review is a separate POST, so refreshing its GET never accepts new stock silently.
                operations.review_draft(pk, actor=request.user, revision=movement.revision)
                return redirect("web:operation-review", pk=pk)
            messages.success(request, "Operação guardada. O stock permanece inalterado.")
            if add_ids and movement.kind != "inventory":
                # Bring the newly selected reference into view even beyond page 1.
                order = list(
                    movement.lines.order_by("reference__name", "pk").values_list(
                        "reference_id", flat=True
                    )
                )
                page = order.index(add_ids[-1]) // 30 + 1
                url = reverse("web:operation-edit", args=[pk])
                return redirect(url + ("?" + urlencode({"page": page}) if page > 1 else ""))
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
    for line in lines:
        line.entered_display = entered_quantity(
            line.boxes, line.units, line.quantity or 0, line.box_capacity
        )
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
            "expired": _expired(movement),
            "header": header,
            "formset": formset,
            "pairs": pairs,
            "lines_page": lines_page,
            "line_params": params.urlencode(),
            "ref_params": ref_params.urlencode(),
            "refs_page": refs_page,
            "filter_form": filter_form,
            "searched": bool(filter_form.is_valid() and filter_form.cleaned_data.get("q")),
            "people": Person.objects.filter(active=True).order_by("name"),
            "counted": movement.lines.filter(counted_quantity__isnull=False).count(),
            "total_lines": movement.lines.count(),
        },
        status=400 if request.method == "POST" else 200,
    )


@operation_required
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters("signature_data")
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
    if movement.kind != "exit":
        form.fields.pop("validation")
        form.fields.pop("signature_data")
    if request.method == "POST" and form.is_valid():
        try:
            confirm_movement(
                pk,
                actor=request.user,
                review_token=form.cleaned_data["token"],
                report_requested=form.cleaned_data.get("report_requested"),
                validation=form.cleaned_data.get("validation"),
                signature_data=form.cleaned_data.get("signature_data"),
            )
        except ValidationError as error:
            _errors(form, error)
        else:
            messages.success(
                request,
                "Operação confirmada. Os relatórios solicitados ou obrigatórios foram guardados.",
            )
            return redirect("web:operation-detail", pk=pk)
    # Show exactly what was reviewed, not silently refreshed quantities.
    plans = []
    stale_review = False
    for line in movement.lines.select_related(
        "reference", "target_location", "target_sector"
    ).order_by("reference__name", "pk"):
        snapshot = movement.review_snapshot.get(str(line.reference_id), {})
        changed = snapshot != reference_state(line.reference)
        stale_review = stale_review or changed
        before = snapshot.get("stock", 0)
        quantity = line.counted_quantity - before if movement.kind == "inventory" else line.quantity
        plans.append(
            {
                "line": line,
                "before": before,
                "quantity": quantity,
                "after": before + quantity,
                "entered_display": entered_quantity(
                    line.boxes, line.units, quantity, line.box_capacity
                ),
                "after_display": "Requer nova conferência"
                if changed
                else stock_quantity(before + quantity, line.box_capacity),
            }
        )
    return render(
        request,
        "web/operations/review.html",
        {
            "section": movement.kind,
            "movement": movement,
            "expired": _expired(movement),
            "form": form,
            "plans": plans,
            "stale_review": stale_review,
        },
        status=400 if request.method == "POST" else 200,
    )


@operation_required
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
                request, "Operação cancelada sem alterar stock. Dados e auditoria preservados."
            )
            return redirect(f"web:{movement.kind}")
    return render(
        request,
        "web/operations/cancel.html",
        {"section": movement.kind, "movement": movement, "error": error},
        status=400 if error else 200,
    )


@permission_required("catalog_manage")
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


@operation_required
@require_http_methods(["GET", "POST"])
def correction(request, pk):
    require_operation(request.user, "inventory")
    original = get_object_or_404(
        visible_movements(request.user, Movement.objects.all()), pk=pk, status="confirmed"
    )
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
        visible_movements(
            request.user,
            Movement.objects.select_related(
                "person", "created_by", "confirmed_by", "correction_of"
            ),
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
    pdfs = list(with_file_status(movement.documents.filter(issued_filter(), kind="pdf")))
    for pdf in pdfs:
        pdf.allow_regenerate = can_regenerate(request.user, pdf)
    return render(
        request,
        "web/operations/detail.html",
        {
            "section": "history",
            "movement": movement,
            "pdfs": pdfs,
        },
    )


@permission_required("catalog_manage")
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
