from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.utils.deprecation import MiddlewareMixin

from .models import User


class RequiredPasswordChangeMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        if not request.user.is_authenticated:
            return None
        if not User.objects.filter(
            pk=request.user.pk, is_active=True, must_change_password=True
        ).exists():
            return None
        if request.resolver_match.view_name in {
            "web:my-account",
            "logout",
            "manifest",
            "service-worker",
            "offline",
        }:
            return None
        if request.method in ("GET", "HEAD"):
            return redirect("web:my-account")
        return HttpResponseForbidden(
            "Altere a palavra-passe temporária em A minha conta antes de continuar.",
            content_type="text/plain; charset=utf-8",
        )
