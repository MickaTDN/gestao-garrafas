from django import template
from django.utils.formats import number_format

register = template.Library()


@register.filter
def box_units(reference):
    if not reference.box_capacity:
        return "Caixa não definida"
    boxes, units = divmod(reference.current_stock, reference.box_capacity)
    return f"{number_format(boxes, use_l10n=True)} cx + {number_format(units, use_l10n=True)} un."
