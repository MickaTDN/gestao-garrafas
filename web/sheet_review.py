"""Administrative pending-sheet screens; writes delegate to transactional services."""

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from consultation.models import PendingSheet
from consultation.review import confirm_sheet, correct_sheet, current, reject_sheet, review_sheet
from inventory.models import AuditEvent, Reference

from .operation_forms import ReviewForm
from .views import administrator_required


class Decision(forms.Form):
    sequence = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    reason = forms.CharField(
        label="Motivo", max_length=4000, required=False, widget=forms.Textarea(attrs={"rows": 2})
    )
    acknowledge_conflicts = forms.BooleanField(
        label="Revi os ficheiros divergentes e conferi explicitamente a versão de trabalho abaixo.",
        required=False,
    )


class Correction(forms.Form):
    person = forms.CharField(label="Pessoa que entregou / levantou", max_length=200)
    physical_date = forms.DateField(
        label="Data física comunicada (não é a data oficial)",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    notes = forms.CharField(
        label="Observações",
        max_length=4000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    reason = forms.CharField(
        label="Motivo obrigatório da correção",
        max_length=4000,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    sequence = forms.IntegerField(min_value=0, widget=forms.HiddenInput)


class Line(forms.Form):
    reference_id = forms.CharField(
        label="Identificador da referência",
        max_length=100,
        widget=forms.TextInput(attrs={"list": "sheet-references"}),
    )
    boxes = forms.IntegerField(label="Caixas", min_value=0, max_value=2147483647, required=False)
    units = forms.IntegerField(
        label="Garrafas soltas", min_value=0, max_value=2147483647, required=False
    )
    box_capacity = forms.IntegerField(
        label="Capacidade por caixa", min_value=1, max_value=2147483647, required=False
    )


class WorkingLineSet(forms.BaseFormSet):
    def add_fields(self, form, index):
        super().add_fields(form, index)
        form.fields["DELETE"].label = "Retirar esta linha apenas da versão de trabalho"


Lines = forms.formset_factory(
    Line,
    formset=WorkingLineSet,
    extra=1,
    can_delete=True,
    min_num=0,
    validate_min=True,
    max_num=31,
    validate_max=True,
    absolute_max=31,
)


class Confirmation(ReviewForm):
    sequence = forms.IntegerField(min_value=0, widget=forms.HiddenInput)


def summary(sheet):
    event, payload = current(sheet)
    receipt = sheet.receipts.filter(outcome="pending").order_by("created_at").first()
    origin = {"owner": "Fábio", "employee": "Daniel"}.get(
        (receipt.authorization if receipt else {}).get("role"), "Origem não identificada"
    )
    return {
        "sheet": sheet,
        "event": event,
        "payload": payload,
        "origin": origin,
        "state": event.get_kind_display() if event else "Recebida · por conferir",
    }


@administrator_required
@require_http_methods(["GET"])
def listing(request, kind):
    sheets = PendingSheet.objects.filter(payload__kind=kind).order_by("received_at", "pk")
    state = request.GET.get("state", "pending")
    if state in ("confirmed", "rejected"):
        sheets = sheets.filter(actions__kind=state)
    elif state != "all":
        state = "pending"
        sheets = sheets.exclude(actions__kind__in=["confirmed", "rejected"])
    page = Paginator(sheets, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "web/sheets/list.html",
        {
            "title": "Entradas pendentes" if kind == "entry" else "Saídas pendentes",
            "section": "pending-" + kind,
            "page_obj": page,
            "rows": [summary(s) for s in page],
            "filter_state": state,
        },
    )


@administrator_required
@sensitive_post_parameters("signature_data")
@require_http_methods(["GET", "POST"])
def detail(request, pk):
    sheet = get_object_or_404(PendingSheet, pk=pk)
    info = summary(sheet)
    event, payload = info["event"], info["payload"]
    sequence = event.sequence if event else 0
    action = request.POST.get("action") if request.method == "POST" else None
    correction = Correction(
        request.POST if action == "correct" else None,
        prefix="correction",
        initial={**payload, "sequence": sequence},
    )
    line_page = Paginator(payload["lines"], 30).get_page(request.GET.get("lines_page"))
    start, end = line_page.start_index() - 1, line_page.end_index()
    lines = Lines(
        request.POST if action == "correct" else None, prefix="lines", initial=list(line_page)
    )
    decision = Decision(
        request.POST if request.method == "POST" and action not in ("correct", "confirm") else None,
        initial={"sequence": sequence},
    )
    confirmation = Confirmation(
        request.POST if action == "confirm" else None,
        initial={"sequence": sequence, "token": event.data.get("token") if event else None},
    )
    if payload["kind"] == "entry":
        confirmation.fields.pop("validation")
        confirmation.fields.pop("signature_data")
    else:
        confirmation.fields.pop("report_requested")
    if request.method == "POST":
        form = (
            correction if action == "correct" else confirmation if action == "confirm" else decision
        )
        try:
            if action == "correct" and correction.is_valid() and lines.is_valid():
                data = correction.cleaned_data
                correct_sheet(
                    pk,
                    actor=request.user,
                    sequence=data["sequence"],
                    reason=data["reason"],
                    values={
                        "person": data["person"],
                        "physical_date": data["physical_date"].isoformat(),
                        "notes": data["notes"],
                        "lines": payload["lines"][:start]
                        + [
                            {
                                key: f.cleaned_data[key]
                                for key in ("reference_id", "boxes", "units", "box_capacity")
                            }
                            for f in lines
                            if f.cleaned_data and not f.cleaned_data.get("DELETE")
                        ]
                        + payload["lines"][end:],
                    },
                )
            elif action in ("review", "reject") and decision.is_valid():
                data = decision.cleaned_data
                if action == "reject":
                    reject_sheet(
                        pk, actor=request.user, sequence=data["sequence"], reason=data["reason"]
                    )
                else:
                    review_sheet(
                        pk,
                        actor=request.user,
                        sequence=data["sequence"],
                        reason=data["reason"],
                        acknowledge_conflicts=data["acknowledge_conflicts"],
                    )
            elif action == "confirm" and confirmation.is_valid():
                data = confirmation.cleaned_data
                confirm_sheet(
                    pk,
                    actor=request.user,
                    sequence=data["sequence"],
                    token=data["token"],
                    confirmed=data["confirm"],
                    report_requested=data.get("report_requested"),
                    validation=data.get("validation"),
                    signature_data=data.get("signature_data"),
                )
            else:
                if action not in ("correct", "review", "reject", "confirm"):
                    form.add_error(None, "Ação inválida.")
                raise ValidationError("Reveja os campos indicados. Nenhum stock foi alterado.")
        except ValidationError as error:
            form.add_error(None, error)
        except PermissionDenied:
            raise
        except Exception:
            # The service already rolled back and audited a safe category; no credentials or signature in UI.
            form.add_error(
                None,
                "Não foi possível concluir. Os dados e o stock foram preservados. Reabra a folha e consulte a auditoria antes de repetir.",
            )
        else:
            messages.success(
                request, "Decisão registada. Só uma confirmação concluída altera o stock."
            )
            return redirect("web:sheet-process", pk=pk)
    refs = {str(r.pk): r for r in Reference.objects.select_related("location", "sector")}
    rows = [
        {"line": line, "reference": refs.get(line["reference_id"])} for line in payload["lines"]
    ]
    reviewed = event and event.kind == "reviewed"
    for row in rows:
        basis = event.data.get("basis", {}).get(row["line"]["reference_id"], {}) if reviewed else {}
        row["reviewed_before"] = basis.get("stock")
        line = row["line"]
        total = (line["boxes"] or 0) * (line["box_capacity"] or 0) + (line["units"] or 0)
        row["total"] = total
        row["reviewed_after"] = (
            basis["stock"] + (total if payload["kind"] == "entry" else -total) if basis else None
        )
    return render(
        request,
        "web/sheets/detail.html",
        {
            **info,
            "section": "pending-" + payload["kind"],
            "rows": rows,
            "correction": correction,
            "lines": lines,
            "line_page": line_page,
            "decision": decision,
            "confirmation": confirmation,
            "closed": event and event.kind in ("confirmed", "rejected"),
            "reviewed": reviewed,
            "official_date": event.data.get("official_date")
            if reviewed
            else timezone.localdate().isoformat(),
            "references": refs.values(),
            "receipts": sheet.receipts.order_by("created_at"),
            "actions": sheet.actions.select_related("actor", "movement").order_by("sequence"),
            "audit": AuditEvent.objects.filter(
                Q(details__sheet_id=str(sheet.pk)) | Q(details__sheet_id=str(sheet.sheet_id))
            )
            .select_related("actor")
            .order_by("created_at", "pk"),
        },
        status=400 if request.method == "POST" else 200,
    )
