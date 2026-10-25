from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods

from accounts.administration import save_profile
from accounts.models import AccessProfile
from accounts.permissions import CAPABILITIES

from .catalog import _errors
from .catalog_forms import StyledFieldsMixin
from .views import administrator_required


class ProfileForm(StyledFieldsMixin, forms.Form):
    name = forms.CharField(max_length=100, label="Nome do perfil")
    active = forms.BooleanField(required=False, initial=True, label="Perfil ativo")
    capabilities = forms.MultipleChoiceField(
        choices=list(CAPABILITIES.items()),
        required=False,
        label="Permissões",
        widget=forms.CheckboxSelectMultiple,
    )
    reason = forms.CharField(max_length=500, label="Motivo da alteração")
    current_password = forms.CharField(
        label="A sua palavra-passe atual", widget=forms.PasswordInput
    )
    confirm = forms.BooleanField(label="Confirmo estas permissões de acesso.")


@administrator_required
@require_GET
def profiles(request):
    return render(
        request,
        "web/profiles/list.html",
        {"section": "settings", "profiles": AccessProfile.objects.order_by("name")},
    )


@administrator_required
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters("current_password")
def edit(request, pk=None):
    profile = get_object_or_404(AccessProfile, pk=pk) if pk else None
    form = ProfileForm(
        request.POST if request.method == "POST" else None,
        initial={
            "name": profile.name,
            "active": profile.active,
            "capabilities": profile.capabilities,
        }
        if profile
        else None,
    )
    if request.method == "POST" and form.is_valid():
        try:
            save_profile(
                actor=request.user,
                profile_id=pk,
                **{key: value for key, value in form.cleaned_data.items() if key != "confirm"},
            )
        except ValidationError as error:
            _errors(form, error)
        else:
            messages.success(
                request,
                "Perfil guardado. As alterações têm efeito nas sessões existentes e preservam o histórico.",
            )
            return redirect("web:profiles")
    return render(
        request,
        "web/users/form.html",
        {
            "section": "settings",
            "title": f"Editar perfil {profile.name}" if profile else "Novo perfil de acesso",
            "form": form,
        },
        status=400 if request.method == "POST" else 200,
    )
