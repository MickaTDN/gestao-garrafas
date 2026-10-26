"""Capabilities are read from persistent accounts, never trusted from a session."""

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import connection

CAPABILITIES = {
    "stock_view": "Consultar stock",
    "history_all": "Consultar todo o histórico",
    "entry": "Registar, conferir e confirmar entradas",
    "exit": "Registar, conferir e confirmar saídas",
    "inventory": "Realizar inventários e correções",
    "reports_view": "Consultar relatórios autorizados",
    "reports_manage": "Eliminar e regenerar relatórios autorizados",
    "catalog_manage": "Gerir referências e alertas",
    "locations_manage": "Gerir localizações e setores",
    "export": "Exportar Stock",
}
SUBSTITUTE = ["stock_view", "entry", "exit", "reports_view"]


def authorization_lock():
    # Common order for account/profile changes and domain writes. No lock on GET.
    if connection.vendor == "postgresql" and connection.in_atomic_block:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [73194622])


def capabilities(actor):
    if not actor or not actor.is_authenticated or not actor.pk or not actor.is_active:
        return set()
    current = (
        get_user_model()
        .objects.select_related("access_profile")
        .filter(pk=actor.pk, is_active=True)
        .first()
    )
    if not current or current.must_change_password:
        return set()
    if current.role == "admin":
        return set(CAPABILITIES) | {"admin"}
    if current.role == "viewer":
        return {"stock_view", "history_all", "reports_view", "export"}
    profile = current.access_profile
    if current.role == "custom" and profile and profile.active:
        return set(profile.capabilities) & set(CAPABILITIES)
    return set()


def require_access(actor, capability):
    authorization_lock()
    allowed = capabilities(actor)
    if capability not in allowed:
        raise PermissionDenied("O seu perfil não permite esta ação.")


def require_operation(actor, kind=None):
    authorization_lock()
    allowed = capabilities(actor)
    if kind not in ("entry", "exit", "inventory") and kind is not None:
        raise PermissionDenied("Operação não autorizada.")
    if not (allowed & {"entry", "exit", "inventory"}) or (kind and kind not in allowed):
        raise PermissionDenied("O seu perfil não permite esta operação.")


def visible_movements(actor, queryset):
    allowed = capabilities(actor)
    if "history_all" in allowed:
        return queryset
    kinds = allowed & {"entry", "exit", "inventory"}
    return queryset.filter(created_by_id=actor.pk, kind__in=kinds) if kinds else queryset.none()


def context(request):
    allowed = capabilities(request.user)
    return {
        "access": {
            **{key: key in allowed for key in CAPABILITIES},
            "admin": "admin" in allowed,
            "history": bool(allowed & {"history_all", "entry", "exit", "inventory"}),
            "operations": bool(allowed & {"entry", "exit", "inventory"}),
        }
    }
