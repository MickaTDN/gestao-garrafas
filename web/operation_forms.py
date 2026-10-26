from django import forms
from django.core import signing
from django.forms import formset_factory
from django.utils import timezone

from inventory.models import Location, Sector
from inventory.ordering import ordered_sectors

from .catalog_forms import SectorSelect, StyledFieldsMixin
from .forms import StockFilterForm


class OperationForm(StyledFieldsMixin, forms.Form):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)


class StartForm(OperationForm):
    inventory_scope = forms.ChoiceField(
        label="Âmbito",
        choices=[
            ("partial", "Parcial — selecionar referências"),
            ("full", "Completo — todas as referências ativas abrangidas"),
        ],
        required=False,
    )
    reason = forms.CharField(
        label="Motivo da correção", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )


class OperationSearchForm(OperationForm):
    q = forms.CharField(required=False, max_length=200, label="Pesquisar referência")


class InventorySearchForm(StockFilterForm):
    q = forms.CharField(required=False, max_length=200, label="Pesquisar referência")

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)
        self.fields["sector"].widget = SectorSelect()
        self.fields["sector"].queryset = ordered_sectors(
            Sector.objects.filter(active=True).select_related("location")
        )


class HeaderForm(OperationForm):
    revision = forms.IntegerField(widget=forms.HiddenInput)
    date = forms.DateField(
        label="Data",
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={"type": "date", "readonly": True}, format="%Y-%m-%d"),
    )
    person_name = forms.CharField(
        label="Pessoa que entregou / levantou",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"list": "people", "autocomplete": "off"}),
    )
    reason = forms.CharField(
        label="Motivo geral / observações", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )


class LineForm(OperationForm):
    id = forms.IntegerField(widget=forms.HiddenInput)
    basis_token = forms.CharField(widget=forms.HiddenInput)
    boxes = forms.IntegerField(label="Caixas", required=False, min_value=0, max_value=2147483647)
    units = forms.IntegerField(
        label="Garrafas soltas", required=False, min_value=0, max_value=2147483647
    )
    reason = forms.CharField(
        label="Motivo da diferença / transferência", required=False, widget=forms.TextInput
    )
    target_location = forms.ModelChoiceField(
        label="Localização após inventário", queryset=Location.objects.all(), required=False
    )
    target_sector = forms.ModelChoiceField(
        label="Setor após inventário",
        queryset=Sector.objects.select_related("location"),
        required=False,
        empty_label="Sem setor definido",
        widget=SectorSelect,
    )
    remove = forms.BooleanField(label="Remover esta linha", required=False)

    def __init__(self, *args, inventory=False, **kwargs):
        super().__init__(*args, **kwargs)
        if self.is_bound and self.data.get("action") in {
            action + str(self.data.get(self.add_prefix("id"), ""))
            for action in ("remove:", "clear:")
        }:
            self.data = self.data.copy()
            self.data[self.add_prefix("boxes")] = ""
            self.data[self.add_prefix("units")] = ""
        if inventory:
            self.fields["target_location"].required = True
            self.fields["target_sector"].queryset = ordered_sectors(
                Sector.objects.select_related("location")
            )
        else:
            for field in ("reason", "target_location", "target_sector"):
                self.fields.pop(field)

    def clean(self):
        data = super().clean()
        location, sector = data.get("target_location"), data.get("target_sector")
        if location and sector and sector.location_id != location.pk:
            self.add_error("target_sector", "O setor não pertence à localização escolhida.")
        return data

    def clean_basis_token(self):
        try:
            return signing.loads(
                self.cleaned_data["basis_token"], salt="count-basis", max_age=86400
            )
        except signing.BadSignature as error:
            raise forms.ValidationError("A página expirou. Reabra o rascunho.") from error


LineFormSet = formset_factory(LineForm, extra=0, max_num=30, validate_max=True, absolute_max=30)


class ReviewForm(OperationForm):
    token = forms.UUIDField(widget=forms.HiddenInput)
    confirm = forms.BooleanField(
        label="Conferi todas as referências e quantidades e confirmo esta operação."
    )
    report_requested = forms.TypedChoiceField(
        label="Pretende gerar e guardar o relatório PDF desta entrada?",
        choices=[("", "Escolha uma opção"), ("yes", "Sim"), ("no", "Não")],
        coerce=lambda value: value == "yes",
    )

    validation = forms.ChoiceField(
        label="Validação da saída",
        choices=[("simple", "Confirmação simples"), ("signed", "Assinatura desenhada")],
        initial="simple",
        required=False,
    )
    signature_data = forms.CharField(required=False, max_length=350000, widget=forms.HiddenInput)

    def clean_validation(self):
        return self.cleaned_data.get("validation") or "simple"
