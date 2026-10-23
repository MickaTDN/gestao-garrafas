from django import forms

from inventory.models import Location, Sector


class StockFilterForm(forms.Form):
    q = forms.CharField(required=False, max_length=200, label="Designação ou código")
    location = forms.ModelChoiceField(
        required=False,
        queryset=Location.objects.filter(active=True).order_by("name"),
        empty_label="Todas as localizações",
        label="Localização",
    )
    sector = forms.ModelChoiceField(
        required=False,
        queryset=Sector.objects.filter(active=True).select_related("location").order_by("location__name", "name"),
        empty_label="Todos os setores",
        label="Setor",
    )

    def clean(self):
        data = super().clean()
        location, sector = data.get("location"), data.get("sector")
        if location and sector and sector.location_id != location.pk:
            self.add_error("sector", "O setor não pertence à localização escolhida.")
        return data


class HistoryFilterForm(forms.Form):
    q = forms.CharField(required=False, max_length=200, label="Referência, pessoa, documento ou etiqueta original")
    start = forms.DateField(required=False, label="De", widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(required=False, label="Até", widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        data = super().clean()
        if data.get("start") and data.get("end") and data["start"] > data["end"]:
            self.add_error("end", "A data final deve ser igual ou posterior à inicial.")
        return data
