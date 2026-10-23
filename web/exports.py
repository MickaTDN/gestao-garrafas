"""Filtered XLSX downloads. No document bytes, credentials or raw import payloads."""

import io

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

from inventory.models import AuditEvent, Location, LocationChange, MovementLine, Reference, Sector

from .catalog_forms import StyledFieldsMixin


class ExportForm(StyledFieldsMixin, forms.Form):
    dataset = forms.ChoiceField(
        label="Dados a exportar",
        choices=[
            ("stock", "Stock atual ativo"),
            ("references", "Referências ativas e inativas"),
            ("locations", "Localizações e setores"),
            ("history", "Histórico confirmado e ajustes"),
            ("transfers", "Transferências de localização e setor"),
        ],
    )
    q = forms.CharField(label="Referência: código ou designação", required=False, max_length=250)
    location = forms.ModelChoiceField(
        label="Localização", queryset=Location.objects.all(), required=False
    )
    sector = forms.ModelChoiceField(label="Setor", queryset=Sector.objects.all(), required=False)
    start = forms.DateField(
        label="Desde", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    end = forms.DateField(
        label="Até", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    state = forms.ChoiceField(
        label="Estado das referências",
        choices=[("", "Ambos"), ("active", "Ativas"), ("inactive", "Inativas")],
        required=False,
    )

    def clean(self):
        data = super().clean()
        if data.get("start") and data.get("end") and data["start"] > data["end"]:
            raise forms.ValidationError("O início do período deve ser anterior ao fim.")
        if (
            data.get("sector")
            and data.get("location")
            and data["sector"].location_id != data["location"].pk
        ):
            raise forms.ValidationError("O setor não pertence à localização escolhida.")
        if data.get("dataset") in ("stock", "references", "locations") and (
            data.get("start") or data.get("end")
        ):
            raise forms.ValidationError("O período aplica-se apenas a histórico e transferências.")
        if data.get("dataset") == "stock" and data.get("state") == "inactive":
            raise forms.ValidationError(
                "O stock normal inclui apenas referências ativas; use Referências para exportar inativas."
            )
        return data


def text_cell(value):
    if not isinstance(value, str):
        return value
    value = ILLEGAL_CHARACTERS_RE.sub("", value)
    if len(value) > 32766:
        raise ValidationError(
            "Um texto excede o limite de célula do Excel. Restrinja os filtros ou reveja o campo."
        )
    if value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@")):
        value = "'" + value
    return value


def equivalent(quantity, capacity):
    return divmod(quantity, capacity) if quantity is not None and capacity else (None, None)


def _reference_filter(query, data, prefix=""):
    if data["q"]:
        query = query.filter(
            Q(**{prefix + "code__icontains": data["q"]})
            | Q(**{prefix + "name__icontains": data["q"]})
        )
    if data["state"]:
        query = query.filter(**{prefix + "active": data["state"] == "active"})
    return query


def export_rows(data):
    kind = data["dataset"]
    if kind in ("stock", "references"):
        refs = _reference_filter(
            Reference.objects.select_related("location", "sector").order_by("code"), data
        )
        if kind == "stock":
            refs = refs.filter(active=True)
        if data["location"]:
            refs = refs.filter(location=data["location"])
        if data["sector"]:
            refs = refs.filter(sector=data["sector"])
        yield [
            "Código",
            "Designação",
            "Estado",
            "Localização atual",
            "Setor atual",
            "Garrafas por caixa",
            "Stock (garrafas)",
            "Caixas completas",
            "Garrafas soltas",
            "Alerta mínimo (vazio = desligado)",
        ]
        for ref in refs.iterator():
            yield [
                ref.code,
                ref.name,
                "Ativa" if ref.active else "Inativa",
                ref.location.name,
                ref.sector.name if ref.sector else None,
                ref.box_capacity,
                ref.current_stock,
                *equivalent(ref.current_stock, ref.box_capacity),
                ref.minimum,
            ]
    elif kind == "locations":
        sectors = Sector.objects.select_related("location").order_by("location_id", "pk")
        locations = Location.objects.all()
        if data["location"]:
            sectors = sectors.filter(location=data["location"])
            locations = locations.filter(pk=data["location"].pk)
        if data["sector"]:
            sectors = sectors.filter(pk=data["sector"].pk)
            locations = locations.filter(pk=data["sector"].location_id)
        if data["q"] or data["state"]:
            refs = _reference_filter(Reference.objects.all(), data)
            locations = locations.filter(references__in=refs).distinct()
            sectors = sectors.filter(references__in=refs).distinct()
        yield ["Localização", "Localização ativa", "Setor", "Setor ativo"]
        seen = set()
        for sector in sectors.iterator():
            seen.add(sector.location_id)
            yield [sector.location.name, sector.location.active, sector.name, sector.active]
        if not data["sector"]:
            for loc in locations.exclude(pk__in=seen):
                yield [loc.name, loc.active, None, None]
    elif kind == "history":
        lines = _reference_filter(
            MovementLine.objects.filter(movement__status="confirmed")
            .select_related(
                "movement__confirmed_by",
                "movement__created_by",
                "movement__person",
                "reference",
                "target_location",
                "target_sector",
            )
            .order_by("movement__date", "movement_id", "reference__code"),
            {**data, "q": ""},
            "reference__",
        )
        if data["q"]:
            lines = lines.filter(
                Q(reference_name__icontains=data["q"]) | Q(reference__code__icontains=data["q"])
            )
        if data["location"]:
            lines = lines.filter(target_location=data["location"])
        if data["sector"]:
            lines = lines.filter(target_sector=data["sector"])
        if data["start"]:
            lines = lines.filter(movement__date__gte=data["start"])
        if data["end"]:
            lines = lines.filter(movement__date__lte=data["end"])
        yield [
            "Movimento",
            "Tipo",
            "Data",
            "Instante (quando conhecido)",
            "Responsável",
            "Pessoa",
            "Código",
            "Designação histórica",
            "Capacidade histórica",
            "Caixas introduzidas",
            "Garrafas soltas introduzidas",
            "Contagem física",
            "Variação (garrafas)",
            "Stock anterior",
            "Stock final",
            "Caixas completas finais",
            "Unidades finais",
            "Motivo",
            "Localização na linha",
            "Setor na linha",
            "Correção de",
            "Documento original",
            "Etiqueta original",
            "Lote Excel",
            "Coluna Excel",
        ]
        for line in lines.iterator():
            mov = line.movement
            actor = mov.confirmed_by or mov.created_by
            yield [
                mov.pk,
                mov.get_kind_display(),
                mov.date,
                mov.occurred_at.isoformat() if mov.occurred_at else None,
                actor.username if actor else None,
                mov.person_name or (mov.person.name if mov.person else None),
                line.reference.code,
                line.reference_name or None,
                line.box_capacity,
                line.boxes,
                line.units,
                line.counted_quantity,
                line.quantity,
                line.stock_before,
                line.stock_after,
                *equivalent(line.stock_after, line.box_capacity),
                line.reason or mov.reason or None,
                line.target_location.name if line.target_location else None,
                line.target_sector.name if line.target_sector else None,
                mov.correction_of_id,
                mov.document_number or None,
                mov.original_label or None,
                mov.import_batch_id,
                mov.source_column,
            ]
    else:
        changes = _reference_filter(
            LocationChange.objects.filter(
                Q(movement__status="confirmed") | Q(movement__isnull=True)
            )
            .select_related("reference", "changed_by")
            .order_by("changed_at", "pk"),
            data,
            "reference__",
        )
        if data["location"]:
            changes = changes.filter(
                Q(location_before=data["location"]) | Q(location_after=data["location"])
            )
        if data["sector"]:
            changes = changes.filter(
                Q(sector_before=data["sector"]) | Q(sector_after=data["sector"])
            )
        if data["start"]:
            changes = changes.filter(changed_at__date__gte=data["start"])
        if data["end"]:
            changes = changes.filter(changed_at__date__lte=data["end"])
        yield [
            "Data",
            "Responsável",
            "Código",
            "Movimento",
            "Localização anterior",
            "Setor anterior",
            "Localização final",
            "Setor final",
            "Motivo",
            "Impacto quantitativo da transferência",
        ]
        for change in changes.iterator():
            yield [
                change.changed_at.isoformat(),
                change.changed_by.username,
                change.reference.code,
                change.movement_id,
                change.before_snapshot.get("location"),
                change.before_snapshot.get("sector"),
                change.after_snapshot.get("location"),
                change.after_snapshot.get("sector"),
                change.reason,
                0,
            ]


def build_workbook(data):
    book = Workbook(write_only=True)
    sheet = book.create_sheet("Dados")
    for index, row in enumerate(export_rows(data)):
        if index > 100000:
            raise ValidationError("A exportação excede 100 000 linhas. Restrinja os filtros.")
        sheet.append([text_cell(value) for value in row])
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


@login_required
@require_GET
def export(request):
    form = ExportForm(request.GET if request.GET else None)
    if request.GET and form.is_valid():
        try:
            payload = build_workbook(form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            AuditEvent.objects.create(
                actor=request.user,
                action="export.created",
                details={"dataset": form.cleaned_data["dataset"]},
            )
            response = HttpResponse(
                payload,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response["Content-Disposition"] = (
                f'attachment; filename="gestao-garrafas-{form.cleaned_data["dataset"]}.xlsx"'
            )
            return response
    return render(
        request,
        "web/export.html",
        {"section": "export", "form": form},
        status=400 if form.is_bound else 200,
    )
