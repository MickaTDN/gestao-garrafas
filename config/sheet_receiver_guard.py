"""Only the private loopback proxy can attest a CA-verified client certificate."""

import hmac
from pathlib import Path
from urllib.parse import unquote

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.x509.oid import ExtendedKeyUsageOID
from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone

from consultation.transport import DevicePrincipal


class SheetReceiverGuard:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        config = getattr(settings, "SHEET_RECEIVER", {})
        if config.get("enabled") is not True:
            return HttpResponse(status=404)
        if (
            request.META.get("REMOTE_ADDR") != "127.0.0.1"
            or request.META.get("HTTP_HOST") != config["origin"].removeprefix("https://")
            or request.META.get("HTTP_X_FORWARDED_PROTO") != "https"
            or not hmac.compare_digest(
                request.META.get("HTTP_X_GVA_PROXY", "").encode(), config["proxy_token"].encode()
            )
        ):
            return HttpResponse("Proxy não autorizado.", status=403)
        if request.path == "/_sheet_receiver_ready" and request.method == "GET":
            return HttpResponse("ready")
        root = config.get("root")
        if root and (
            (Path(root) / "maintenance.json").exists()
            or not (Path(root) / "runtime/receiver/approved").is_file()
        ):
            return HttpResponse("Manutenção ou acesso desativado.", status=503)
        if (
            request.path != "/v1/pending-sheets"
            or request.META.get("HTTP_ORIGIN") != config["stock_origin"]
            or request.META.get("HTTP_X_GVA_VERIFIED") != "SUCCESS"
            or request.META.get("HTTP_COOKIE")
            or request.META.get("HTTP_AUTHORIZATION")
        ):
            return HttpResponse("Origem ou canal não autorizado.", status=403)
        try:
            pem = request.META.get("HTTP_X_GVA_CERT", "")
            if not 1 <= len(pem) <= 16000:
                raise ValueError
            certificate = x509.load_pem_x509_certificate(unquote(pem).encode("ascii"))
            now = timezone.now()
            if (
                not certificate.not_valid_before_utc <= now <= certificate.not_valid_after_utc
                or certificate.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
                or ExtendedKeyUsageOID.CLIENT_AUTH
                not in certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
            ):
                raise ValueError
            fingerprint = certificate.fingerprint(hashes.SHA256()).hex()
            request.sheet_principal = DevicePrincipal(config["devices"][fingerprint], fingerprint)
        except (ValueError, KeyError, x509.ExtensionNotFound):
            return HttpResponse("Certificado individual não autorizado.", status=403)
        response = self.get_response(request)
        response["Access-Control-Allow-Origin"] = config["stock_origin"]
        response["Access-Control-Allow-Credentials"] = "true"
        response["Vary"] = "Origin"
        response["Cache-Control"] = "no-store"
        return response
