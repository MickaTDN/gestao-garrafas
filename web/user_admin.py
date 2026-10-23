from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods

from accounts.administration import change_account, create_account

from .catalog import _errors
from .catalog_forms import StyledFieldsMixin
from .views import _page, administrator_required

User = get_user_model()


class AccountCreateForm(StyledFieldsMixin, UserCreationForm):
    current_password = forms.CharField(
        label="A sua palavra-passe atual", widget=forms.PasswordInput
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ["username", "role"]
        labels = {"username": "Utilizador", "role": "Perfil"}


class AccountChangeForm(StyledFieldsMixin, forms.Form):
    role = forms.ChoiceField(label="Perfil", choices=User.Role.choices)
    active = forms.BooleanField(label="Conta ativa", required=False)
    reason = forms.CharField(label="Motivo da alteração", max_length=500)
    current_password = forms.CharField(
        label="A sua palavra-passe atual", widget=forms.PasswordInput
    )
    confirm = forms.BooleanField(label="Confirmo esta alteração de acesso.")


@administrator_required
@require_GET
def accounts(request):
    return render(
        request,
        "web/users/list.html",
        {"section": "settings", **_page(request, User.objects.order_by("username"))},
    )


@administrator_required
@sensitive_post_parameters("password1", "password2", "current_password")
@require_http_methods(["GET", "POST"])
def create(request):
    form = AccountCreateForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            create_account(
                actor=request.user,
                username=form.cleaned_data["username"],
                password=form.cleaned_data["password1"],
                role=form.cleaned_data["role"],
                current_password=form.cleaned_data["current_password"],
            )
        except ValidationError as error:
            _errors(form, error)
        else:
            messages.success(request, "Utilizador criado sem credenciais predefinidas.")
            return redirect("web:users")
    return render(
        request,
        "web/users/form.html",
        {"section": "settings", "title": "Criar utilizador", "form": form},
        status=400 if request.method == "POST" else 200,
    )


@administrator_required
@sensitive_post_parameters("current_password")
@require_http_methods(["GET", "POST"])
def edit(request, pk):
    account = get_object_or_404(User, pk=pk)
    form = AccountChangeForm(
        request.POST if request.method == "POST" else None,
        initial={"role": account.role, "active": account.is_active},
    )
    if request.method == "POST" and form.is_valid():
        try:
            change_account(
                actor=request.user,
                account_id=pk,
                role=form.cleaned_data["role"],
                active=form.cleaned_data["active"],
                current_password=form.cleaned_data["current_password"],
                reason=form.cleaned_data["reason"],
            )
        except ValidationError as error:
            _errors(form, error)
        else:
            messages.success(request, "Acesso atualizado. Identidade e histórico preservados.")
            return redirect("web:users")
    return render(
        request,
        "web/users/form.html",
        {"section": "settings", "title": f"Gerir {account.username}", "form": form},
        status=400 if request.method == "POST" else 200,
    )
