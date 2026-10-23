from django import forms
from django.db.models import Q

from inventory.models import Location, Reference, Sector


class StyledFieldsMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "input"


class ReferenceForm(StyledFieldsMixin, forms.ModelForm):
    alert_enabled = forms.BooleanField(required=False, label="Ativar alerta de stock mínimo")
    minimum = forms.IntegerField(
        required=False, min_value=0, label="Stock mínimo em garrafas",
        help_text="Só é utilizado quando o alerta está ligado nesta referência.",
    )

    class Meta:
        model = Reference
        fields = ["name", "box_capacity", "location", "sector", "minimum"]
        labels = {
            "name": "Designação", "box_capacity": "Garrafas por caixa",
            "location": "Localização", "sector": "Setor",
        }
        help_texts = {"box_capacity": "Deixe vazio se a capacidade ainda não estiver definida."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(["name", "box_capacity", "location", "sector", "alert_enabled", "minimum"])
        self.fields["alert_enabled"].initial = self.instance.minimum is not None
        self.fields["location"].queryset = Location.objects.filter(
            Q(active=True) | Q(pk=self.instance.location_id)
        ).order_by("name")
        self.fields["sector"].queryset = Sector.objects.filter(
            Q(active=True) | Q(pk=self.instance.sector_id)
        ).select_related("location").order_by("location__name", "name")
        self.fields["sector"].empty_label = "Setor por definir"
        # An inactive alert discards even a forged value; it never creates a
        # minimum on a reference the administrator did not select.
        if self.is_bound and not self.data.get("alert_enabled"):
            self.data = self.data.copy()
            self.data["minimum"] = ""

    def clean_name(self):
        return " ".join(self.cleaned_data["name"].split())

    def clean(self):
        data = super().clean()
        if data.get("alert_enabled") and data.get("minimum") is None:
            self.add_error("minimum", "Defina o mínimo para ativar este alerta.")
        if not data.get("alert_enabled"):
            data["minimum"] = None
        sector, location = data.get("sector"), data.get("location")
        if location and sector and sector.location_id != location.pk:
            self.add_error("sector", "O setor não pertence à localização escolhida.")
        return data


class ReferenceSearchForm(forms.Form):
    q = forms.CharField(required=False, max_length=200, label="Designação ou código")
    state = forms.ChoiceField(
        required=False, label="Estado", choices=[("", "Todas"), ("active", "Ativas"), ("inactive", "Inativas")],
    )


class ReferenceStateForm(forms.Form):
    active = forms.TypedChoiceField(choices=[("0", "Inativa"), ("1", "Ativa")], coerce=lambda value: value == "1")


class LocationForm(StyledFieldsMixin, forms.ModelForm):
    class Meta:
        model = Location
        fields = ["name"]
        labels = {"name": "Designação da localização"}

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        if Location.objects.filter(name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Já existe uma localização com esta designação.")
        return name


class SectorForm(StyledFieldsMixin, forms.ModelForm):
    class Meta:
        model = Sector
        fields = ["name", "location"]
        labels = {"name": "Designação do setor", "location": "Localização"}

    def clean_name(self):
        return " ".join(self.cleaned_data["name"].split())

    def clean(self):
        data = super().clean()
        location, name = data.get("location"), data.get("name")
        if location and name and Sector.objects.filter(location=location, name__iexact=name).exclude(pk=self.instance.pk).exists():
            self.add_error("name", "Já existe um setor com esta designação na localização.")
        return data
