from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.views.decorators.debug import sensitive_variables

from inventory.models import AuditEvent
from inventory.services import require_administrator


def _lock(actor):
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [73194622])
    current = get_user_model().objects.select_for_update().get(pk=actor.pk)
    require_administrator(current)
    return current


def _verify(actor, password):
    if not actor.check_password(password):
        raise ValidationError("Confirme a sua palavra-passe atual.")


@sensitive_variables("password", "current_password")
@transaction.atomic
def create_account(*, actor, username, password, role, current_password):
    require_administrator(actor)
    actor = _lock(actor)
    _verify(actor, current_password)
    User = get_user_model()
    if role not in User.Role.values:
        raise ValidationError("Perfil inválido.")
    if User.objects.filter(username__iexact=username).exists():
        raise ValidationError("Já existe um utilizador com esse identificador.")
    account = User(username=username, role=role)
    password_validation.validate_password(password, user=account)
    account.set_password(password)
    account.full_clean()
    account.save()
    AuditEvent.objects.create(
        actor=actor, action="account.created", details={"user_id": account.pk, "role": role}
    )
    return account


@sensitive_variables("current_password")
@transaction.atomic
def change_account(*, actor, account_id, role, active, current_password, reason):
    require_administrator(actor)
    actor = _lock(actor)
    _verify(actor, current_password)
    User = get_user_model()
    if role not in User.Role.values or type(active) is not bool or not reason.strip():
        raise ValidationError("Defina um perfil válido, estado e motivo da alteração.")
    account = User.objects.select_for_update().get(pk=account_id)
    if account.pk == actor.pk and (not active or role != User.Role.ADMIN):
        raise ValidationError(
            "Não pode desativar a sua própria conta nem retirar o seu próprio perfil de administrador."
        )
    if (
        account.is_administrator
        and (not active or role != User.Role.ADMIN)
        and not User.objects.filter(role="admin", is_active=True).exclude(pk=account.pk).exists()
    ):
        raise ValidationError("É obrigatório manter um administrador ativo.")
    before = {"role": account.role, "active": account.is_active}
    account.role, account.is_active = role, active
    account.save(update_fields=["role", "is_active"])
    AuditEvent.objects.create(
        actor=actor,
        action="account.updated",
        details={
            "user_id": account.pk,
            "before": before,
            "after": {"role": role, "active": active},
            "reason": reason.strip(),
        },
    )
    return account
