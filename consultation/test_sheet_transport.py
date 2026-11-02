import base64
import hashlib
import importlib
import json
import secrets
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from urllib.parse import quote

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.db.migrations.exceptions import IrreversibleError
from django.test import (
    Client,
    TestCase,
    TransactionTestCase,
    override_settings,
    skipUnlessDBFeature,
)
from django.utils import timezone

from consultation.models import PendingSheet, SheetReceipt
from consultation.sheets import receive_sheet
from consultation.test_sheets import SheetFixtures
from consultation.transport import DevicePrincipal, accept_upload
from inventory.models import Document, Movement


def leaf_certificate(*, expired=False):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "synthetic-device")])
    now = datetime.now(dt_timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=2))
        .not_valid_after(now - timedelta(days=1) if expired else now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return certificate


class TransportFixtures(SheetFixtures):
    def prepare_transport(self):
        self.prepare()
        self.origin_key = ec.generate_private_key(ec.SECP256R1())
        (Path(self.temp.name) / "signing.pem").write_bytes(
            self.origin_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        self.certificate = leaf_certificate()
        self.fingerprint = self.certificate.fingerprint(hashes.SHA256()).hex()
        self.principal = DevicePrincipal(str(self.device.pk), self.fingerprint)
        self.cfg = {
            "enabled": True,
            "origin": "https://receiver.synthetic.test:8446",
            "stock_origin": "https://stock.synthetic.test:8444",
            "proxy_token": secrets.token_hex(32),
            "devices": {self.fingerprint: str(self.device.pk)},
        }

    def ack(self, envelope):
        raw = base64.urlsafe_b64decode(envelope["payload"] + "==")
        signature = base64.urlsafe_b64decode(envelope["signature"] + "==")
        self.origin_key.public_key().verify(
            encode_dss_signature(int.from_bytes(signature[:32]), int.from_bytes(signature[32:])),
            b"vertente-sheet-receipt-v1\0" + raw,
            ec.ECDSA(hashes.SHA256()),
        )
        return json.loads(raw)


class SheetTransportTests(TransportFixtures, TestCase):
    def setUp(self):
        self.prepare_transport()

    def headers(self, **changes):
        return {
            "HTTP_HOST": self.cfg["origin"].removeprefix("https://"),
            "HTTP_ORIGIN": self.cfg["stock_origin"],
            "HTTP_X_FORWARDED_PROTO": "https",
            "HTTP_X_GVA_PROXY": self.cfg["proxy_token"],
            "HTTP_X_GVA_VERIFIED": "SUCCESS",
            "HTTP_X_GVA_REQUEST": str(uuid.uuid4()),
            "HTTP_X_GVA_CERT": quote(
                self.certificate.public_bytes(serialization.Encoding.PEM).decode(), safe=""
            ),
            **changes,
        }

    def api(self):
        return self.settings(
            ROOT_URLCONF="config.sheet_receiver_urls",
            SHEET_RECEIVER=self.cfg,
            ALLOWED_HOSTS=["receiver.synthetic.test"],
            MIDDLEWARE=[
                "config.sheet_receiver_guard.SheetReceiverGuard",
                "django.middleware.csrf.CsrfViewMiddleware",
            ],
        )

    def test_wifi_and_file_share_exact_deduplication_without_administrator_impersonation(self):
        raw = self.packet()
        nonce = str(uuid.uuid4())
        proof = self.ack(accept_upload(raw, principal=self.principal, request_id=nonce))
        self.assertEqual(proof["outcome"], "pending")
        self.assertEqual(proof["request_id"], nonce)
        self.assertEqual(proof["file_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertIsNone(SheetReceipt.objects.get().actor_id)
        self.assertEqual(
            SheetReceipt.objects.get().authorization["certificate_sha256"], self.fingerprint
        )
        self.assertEqual(receive_sheet(raw, actor=self.admin).outcome, "duplicate")
        repeated = self.ack(
            accept_upload(raw, principal=self.principal, request_id=str(uuid.uuid4()))
        )
        self.assertEqual(repeated["outcome"], "duplicate")
        self.assertEqual(PendingSheet.objects.count(), 1)
        self.assertEqual(get_user_model().objects.count(), 2)
        self.assertFalse(Movement.objects.exists())
        self.assertFalse(Document.objects.exists())
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 12)

    def test_lost_response_retry_has_fresh_signed_nonce_and_same_sheet(self):
        raw = self.packet()
        first = self.ack(accept_upload(raw, principal=self.principal, request_id=str(uuid.uuid4())))
        second = self.ack(
            accept_upload(raw, principal=self.principal, request_id=str(uuid.uuid4()))
        )
        self.assertNotEqual(first["request_id"], second["request_id"])
        self.assertEqual(first["sheet_id"], second["sheet_id"])
        self.assertEqual(second["outcome"], "duplicate")

    def test_conflict_ack_is_bound_to_incoming_revision_and_hash(self):
        receive_sheet(self.packet(), actor=self.admin)
        raw = self.packet({**self.payload, "revision": 2, "notes": "Divergência sintética"})
        proof = self.ack(accept_upload(raw, principal=self.principal, request_id=str(uuid.uuid4())))
        self.assertEqual((proof["outcome"], proof["revision"]), ("conflict", 2))
        self.assertEqual(proof["file_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(PendingSheet.objects.get().revision, 1)

    def test_signing_failure_rolls_back_reception_before_any_ack(self):
        with patch("consultation.transport.signed_snapshot", side_effect=RuntimeError("synthetic")):
            with self.assertRaises(RuntimeError):
                accept_upload(self.packet(), principal=self.principal, request_id=str(uuid.uuid4()))
        self.assertFalse(PendingSheet.objects.exists())
        self.assertFalse(SheetReceipt.objects.exists())

    def test_wrong_device_signature_corruption_and_revocation_reject(self):
        wrong = DevicePrincipal(str(uuid.uuid4()), self.fingerprint)
        with self.assertRaises(ValidationError):
            accept_upload(self.packet(), principal=wrong, request_id=str(uuid.uuid4()))
        for raw in [b"{}", self.packet()[:-10], self.packet(key=self.other)]:
            with self.assertRaises(ValidationError):
                accept_upload(raw, principal=self.principal, request_id=str(uuid.uuid4()))
        self.device.revoked_at = timezone.now()
        self.device.save(update_fields=["revoked_at"])
        with self.assertRaises(ValidationError):
            accept_upload(self.packet(), principal=self.principal, request_id=str(uuid.uuid4()))
        self.assertFalse(PendingSheet.objects.exists())

    def test_http_machine_endpoint_is_opt_in_and_rejects_forged_headers_cookies_and_origin(self):
        client = Client(enforce_csrf_checks=True)
        with self.api():
            for bad in [
                {"HTTP_X_GVA_PROXY": "wrong"},
                {"REMOTE_ADDR": "192.168.1.25"},
                {"HTTP_ORIGIN": "https://evil.synthetic.test"},
                {"HTTP_X_GVA_VERIFIED": "FAILED"},
                {"HTTP_X_GVA_CERT": "forged"},
                {"HTTP_COOKIE": "gva_session=forged"},
                {"HTTP_X_FORWARDED_PROTO": "http"},
                {"HTTP_AUTHORIZATION": "Bearer forged"},
            ]:
                response = client.post(
                    "/v1/pending-sheets",
                    self.packet(),
                    content_type="application/json",
                    **self.headers(**bad),
                )
                self.assertEqual(response.status_code, 403)
            with override_settings(SHEET_RECEIVER={**self.cfg, "enabled": False}):
                self.assertEqual(
                    client.post(
                        "/v1/pending-sheets",
                        b"{}",
                        content_type="application/json",
                        **self.headers(),
                    ).status_code,
                    404,
                )
            self.assertFalse(PendingSheet.objects.exists())
            response = client.post(
                "/v1/pending-sheets",
                self.packet(),
                content_type="application/json",
                **self.headers(),
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Access-Control-Allow-Origin"], self.cfg["stock_origin"])
            self.assertEqual(response["Cache-Control"], "no-store")
            self.assertEqual(response.cookies, {})
            self.ack(response.json())

    def test_preflight_bounds_unmapped_expired_certificate_and_other_urls_are_rejected(self):
        with self.api():
            headers = self.headers(
                HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
                HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type,x-gva-request",
            )
            self.assertEqual(self.client.options("/v1/pending-sheets", **headers).status_code, 204)
            self.assertEqual(
                self.client.options(
                    "/v1/pending-sheets",
                    **{**headers, "HTTP_ACCESS_CONTROL_REQUEST_HEADERS": "authorization"},
                ).status_code,
                403,
            )
            other = leaf_certificate()
            for certificate in [other, leaf_certificate(expired=True)]:
                header = quote(
                    certificate.public_bytes(serialization.Encoding.PEM).decode(), safe=""
                )
                self.assertEqual(
                    self.client.post(
                        "/v1/pending-sheets",
                        b"{}",
                        content_type="application/json",
                        **self.headers(HTTP_X_GVA_CERT=header),
                    ).status_code,
                    403,
                )
            self.assertEqual(
                self.client.post(
                    "/v1/pending-sheets",
                    b"x" * (1024 * 1024 + 1),
                    content_type="application/json",
                    **self.headers(),
                ).status_code,
                413,
            )
            self.assertEqual(self.client.get("/entradas/", **self.headers()).status_code, 403)

    def test_schema_reverse_does_not_discard_device_receipts(self):
        accept_upload(self.packet(), principal=self.principal, request_id=str(uuid.uuid4()))
        module = importlib.import_module("consultation.migrations.0005_wifi_receipt_actor")
        with self.assertRaises(IrreversibleError):
            module.protect_reverse(apps, None)


@skipUnlessDBFeature("has_select_for_update")
class SheetTransportConcurrencyTests(TransportFixtures, TransactionTestCase):
    def setUp(self):
        self.prepare_transport()

    def test_two_connections_accept_one_pending_with_verifiable_receipts(self):
        barrier = Barrier(2)
        raw = self.packet()

        def send(_):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return accept_upload(raw, principal=self.principal, request_id=str(uuid.uuid4()))
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [self.ack(proof)["outcome"] for proof in pool.map(send, range(2))]
        self.assertCountEqual(results, ["pending", "duplicate"])
        self.assertEqual(PendingSheet.objects.count(), 1)
        self.assertEqual(SheetReceipt.objects.count(), 2)
        self.assertFalse(Movement.objects.exists())
