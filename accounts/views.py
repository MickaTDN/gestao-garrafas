import ipaddress

from django.conf import settings
from django.contrib.auth.views import LoginView
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters

from .security import reserve_login_attempt, successful_login


@method_decorator(sensitive_post_parameters("password"), name="dispatch")
class ProtectedLoginView(LoginView):
    """Reserve attempts before checking passwords, including concurrent requests."""

    def post(self, request, *args, **kwargs):
        # REMOTE_ADDR is supplied by the trusted server, never X-Forwarded-For.
        username = request.POST.get("username", "")[:150]
        address = request.META.get("REMOTE_ADDR", "")
        if address in settings.LOGIN_TRUSTED_PROXY_ADDRESSES:
            try:
                address = str(ipaddress.ip_address(request.META.get("HTTP_X_FORWARDED_FOR", "")))
            except ValueError:
                pass
        if not reserve_login_attempt(username, address):
            form = self.get_form_class()(request=request, data={})
            form.is_valid()
            form.errors.clear()
            form.add_error(None, "Demasiadas tentativas. Aguarde antes de voltar a tentar.")
            response = self.render_to_response(self.get_context_data(form=form), status=429)
            response["Retry-After"] = str(settings.LOGIN_WINDOW_SECONDS)
            return response
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        successful_login(form.cleaned_data["username"])
        return super().form_valid(form)
