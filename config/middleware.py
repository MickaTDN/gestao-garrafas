from django.utils.cache import patch_vary_headers


class PrivacyMiddleware:
    """Private pages/bytes must never enter browser or shared HTTP caches."""

    public_paths = {"/manifest.webmanifest", "/service-worker.js", "/offline/"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path not in self.public_paths and not request.path.startswith("/static/"):
            response["Cache-Control"] = "private, no-store, max-age=0, must-revalidate"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
            patch_vary_headers(response, ("Cookie",))
        response["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response
