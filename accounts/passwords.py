"""Native Django password forms, fresh authority, independent bounded attempts."""

from django import forms
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.views.decorators.debug import sensitive_variables

from inventory.models import AuditEvent

from .models import User
from .permissions import authorization_lock, require_access
from .security import reserve_password_attempt


class PasswordAttemptsExceeded(ValidationError):
    pass


class OwnPasswordForm(PasswordChangeForm):
    def __init__(self, user, *args, **kwargs):
        kwargs.setdefault("label_suffix", "")
        super().__init__(user, *args, **kwargs)
        for name, label in [
            ("old_password", "Palavra-passe atual"),
            ("new_password1", "Nova palavra-passe"),
            ("new_password2", "Confirmar nova palavra-passe"),
        ]:
            self.fields[name].label = label

    @sensitive_variables()
    def clean(self):
        data = super().clean()
        value = data.get("new_password2")
        if value and self.user.check_password(value):
            self.add_error(
                "new_password2", "Escolha uma palavra-passe diferente da atual ou temporária."
            )
        return data


class ResetPasswordForm(SetPasswordForm):
    current_password = forms.CharField(
        label="A sua palavra-passe de Administrador",
        widget=forms.PasswordInput,
        strip=False,
    )
    confirm = forms.BooleanField(
        label="Confirmo a reposição e a alteração obrigatória no próximo início de sessão."
    )

    def __init__(self, user, *args, administrator=None, **kwargs):
        kwargs.setdefault("label_suffix", "")
        super().__init__(user, *args, **kwargs)
        self.administrator = administrator
        self.fields["new_password1"].label = "Palavra-passe temporária"
        self.fields["new_password2"].label = "Confirmar palavra-passe temporária"

    @sensitive_variables()
    def clean_current_password(self):
        value = self.cleaned_data["current_password"]
        if not self.administrator.check_password(value):
            raise forms.ValidationError("A palavra-passe de Administrador não está correta.")
        return value


def _attempt(actor, purpose, address):
    if (
        not actor
        or not actor.is_authenticated
        or not User.objects.filter(pk=actor.pk, is_active=True).exists()
    ):
        raise PermissionDenied("Conta indisponível.")
    # Reserve OUTSIDE the mutation transaction so invalid forms cannot roll back
    # their failed attempts. Login uses separate HMAC namespaces and limits.
    if not reserve_password_attempt(actor.pk, purpose, address):
        raise PasswordAttemptsExceeded("Demasiadas tentativas. Aguarde antes de voltar a tentar.")


@sensitive_variables()
def change_own_password(*, actor, data, address=""):
    _attempt(actor, "change", address)
    with transaction.atomic():
        authorization_lock()
        current = User.objects.select_for_update().get(pk=actor.pk)
        if not current.is_active:
            raise PermissionDenied("Conta indisponível.")
        form = OwnPasswordForm(current, data=data)
        if form.is_valid():
            current.must_change_password = False
            form.save()
            AuditEvent.objects.create(
                actor=current, action="account.password_changed", details={"user_id": current.pk}
            )
        return form


@sensitive_variables()
def reset_password(*, actor, account_id, data, address=""):
    require_access(actor, "admin")
    if actor.pk == account_id:
        raise ValidationError("Para alterar a sua própria palavra-passe, utilize A minha conta.")
    _attempt(actor, "reset", address)
    with transaction.atomic():
        require_access(actor, "admin")
        administrator = User.objects.select_for_update().get(pk=actor.pk)
        account = User.objects.select_for_update().get(pk=account_id)
        form = ResetPasswordForm(account, data=data, administrator=administrator)
        if form.is_valid():
            account.must_change_password = True
            form.save()
            AuditEvent.objects.create(
                actor=administrator,
                action="account.password_reset",
                details={"user_id": account.pk, "change_required": True},
            )
        return form
