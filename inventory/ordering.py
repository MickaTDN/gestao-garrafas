"""Numeric configured sectors first; named sectors then unassigned, per location."""

from django.db.models import Case, DecimalField, F, Value, When
from django.db.models.functions import Cast, Lower, Replace


def sector_number(field):
    return Case(
        When(
            **{field + "__iregex": r"^(Setor\s*)?[0-9]+$"},
            then=Cast(
                Replace(Lower(field), Value("setor"), Value("")),
                DecimalField(max_digits=100, decimal_places=0),
            ),
        ),
        output_field=DecimalField(max_digits=100, decimal_places=0),
    )


def ordered_sectors(queryset):
    return queryset.annotate(_sector_number=sector_number("name")).order_by(
        "location__name", F("_sector_number").asc(nulls_last=True), "name", "pk"
    )


def inventory_order(queryset, prefix=""):
    return queryset.annotate(_sector_number=sector_number(prefix + "sector__name")).order_by(
        prefix + "location__name",
        F("_sector_number").asc(nulls_last=True),
        F(prefix + "sector__name").asc(nulls_last=True),
        prefix + "name",
        "pk",
    )
