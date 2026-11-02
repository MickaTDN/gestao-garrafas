from unittest.mock import Mock

from django.conf import settings
from django.http import HttpResponse
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings

from config.native_wifi_guard import NativeWifiGuard

from . import tests_operations


@override_settings(WIFI_ORIGIN="https://gestao.example.internal:8443", WIFI_PROXY_TOKEN="a" * 64)
class NativeWifiGuardTests(SimpleTestCase):
    def test_only_exact_proxy_origin_and_secret_can_reach_django(self):
        factory = RequestFactory()
        headers = {
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_HOST": "gestao.example.internal:8443",
            "HTTP_X_FORWARDED_PROTO": "https",
            "HTTP_X_GVA_PROXY": "a" * 64,
        }
        downstream = Mock(return_value=HttpResponse("allowed"))
        gate = NativeWifiGuard(downstream)
        self.assertEqual(gate(factory.get("/", **headers)).status_code, 200)
        for changes in (
            {"REMOTE_ADDR": "192.168.20.50"},
            {"HTTP_X_GVA_PROXY": ""},
            {"HTTP_X_GVA_PROXY": "é"},
            {"HTTP_HOST": "localhost"},
            {"HTTP_X_FORWARDED_PROTO": "http"},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(
                    gate(factory.post("/entradas/", **{**headers, **changes})).status_code, 400
                )
        self.assertEqual(downstream.call_count, 1)


@override_settings(
    WIFI_ORIGIN="https://gestao.synthetic.test:8443",
    WIFI_PROXY_TOKEN="a" * 64,
    ALLOWED_HOSTS=["gestao.synthetic.test"],
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    SESSION_COOKIE_SECURE=True,
    CSRF_COOKIE_SECURE=True,
    SESSION_COOKIE_NAME="gva_wifi_session",
    CSRF_COOKIE_NAME="gva_wifi_csrf",
    MIDDLEWARE=["config.native_wifi_guard.NativeWifiGuard", *settings.MIDDLEWARE],
)
class NativeWifiOperationsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        tests_operations.OperationWebTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.client = Client(
            REMOTE_ADDR="127.0.0.1",
            HTTP_HOST="gestao.synthetic.test:8443",
            HTTP_X_FORWARDED_PROTO="https",
            HTTP_X_GVA_PROXY="a" * 64,
        )
        self.client.force_login(self.admin)

    draft = tests_operations.OperationWebTests.draft
    payload = staticmethod(tests_operations.OperationWebTests.payload)
    post_edit = tests_operations.OperationWebTests.post_edit
    reviewed = tests_operations.OperationWebTests.reviewed
    test_entry_and_duplicate_confirmation = tests_operations.OperationWebTests.test_entry_review_requires_explicit_report_choice_and_confirmation
    test_exit_signature_validation = tests_operations.OperationWebTests.test_exit_simple_and_signed_choices_require_valid_signature
