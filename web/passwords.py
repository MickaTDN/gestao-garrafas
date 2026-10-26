from django import forms
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from accounts.models import User
from accounts.passwords import (
    OwnPasswordForm,
    PasswordAttemptsExceeded,
    ResetPasswordForm,
    change_own_password,
    reset_password,
)

from .views import administrator_required


@login_required
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def own(request):
    form = OwnPasswordForm(request.user)
    status = 200
    if request.method == "POST":
        try:
            form = change_own_password(
                actor=request.user, data=request.POST, address=request.META.get("REMOTE_ADDR", "")
            )
        except PasswordAttemptsExceeded as error:
            form = forms.Form(data={})
            form.is_valid()
            form.add_error(None, error)
            status = 429
        else:
            if form.is_valid():
                update_session_auth_hash(request, form.user)
                messages.success(
                    request,
                    "Palavra-passe alterada. A sessão atual foi preservada; as sessões anteriores deixam de ser válidas.",
                )
                return redirect("web:my-account")
            status = 400
    response = render(
        request,
        "web/password.html",
        {
            "section": "settings",
            "form": form,
            "own": True,
            "required": request.user.must_change_password,
        },
        status=status,
    )
    if status == 429:
        from django.conf import settings

        response["Retry-After"] = str(settings.LOGIN_WINDOW_SECONDS)
    return response


@administrator_required
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def reset(request, pk):
    account = get_object_or_404(User, pk=pk)
    if account.pk == request.user.pk:
        return redirect("web:my-account")
    form = ResetPasswordForm(account, administrator=request.user)
    status = 200
    if request.method == "POST":
        try:
            form = reset_password(
                actor=request.user,
                account_id=pk,
                data=request.POST,
                address=request.META.get("REMOTE_ADDR", ""),
            )
        except PasswordAttemptsExceeded as error:
            form = forms.Form(data={})
            form.is_valid()
            form.add_error(None, error)
            status = 429
        else:
            if form.is_valid():
                messages.success(
                    request,
                    "Palavra-passe temporária definida. O utilizador terá de a alterar no próximo início de sessão. O estado de ativação da conta foi preservado.",
                )
                return redirect("web:users")
            status = 400
    return render(
        request,
        "web/password.html",
        {"section": "settings", "form": form, "account": account},
        status=status,
    )
