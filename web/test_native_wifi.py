from unittest.mock import Mock

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from config.native_wifi_guard import NativeWifiGuard


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
