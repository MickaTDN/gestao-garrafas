import os
import runpy
import sys
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from config.wifi_middleware import WifiProxyMiddleware
from tests.windows.test_profile import ENV

ROOT = Path(__file__).resolve().parents[2]
WIFI = {
    **ENV,
    "GG_ANDROID_WIFI": "synthetic-wifi-v1",
    "GG_WIFI_HOST": "garrafas.wifi.example.invalid",
    "GG_HTTPS_PORT": "8443",
    "GG_PROXY_SUBNET": "172.29.86.0/29",
    "GG_PROXY_IP": "172.29.86.2",
    "GG_APP_IP": "172.29.86.3",
}


def profile(**changes):
    # Importing the parent profile must not leak into the other settings tests.
    with (
        patch.dict(os.environ, {**WIFI, **changes}),
        patch.dict(sys.modules),
        patch("pathlib.Path.read_text", return_value="synthetic-wifi-key"),
    ):
        sys.modules.pop("config.windows_local", None)
        return runpy.run_module("config.android_wifi")


class WifiProfileTests(SimpleTestCase):
    def test_explicit_synthetic_profile_required(self):
        for changes in ({"GG_ANDROID_WIFI": ""}, {"DB_NAME": "garrafas"}, {"DB_HOST": "localhost"}):
            with self.subTest(changes=changes), self.assertRaises(ImproperlyConfigured):
                profile(**changes)

    def test_exact_hosts_origin_secure_cookies_and_no_debug(self):
        result = profile(DJANGO_DEBUG="1", DJANGO_ALLOWED_HOSTS="*", TRUST_HTTPS_PROXY="0")
        self.assertFalse(result["DEBUG"])
        self.assertEqual(result["ALLOWED_HOSTS"], [WIFI["GG_WIFI_HOST"]])
        self.assertEqual(
            result["CSRF_TRUSTED_ORIGINS"], ["https://garrafas.wifi.example.invalid:8443"]
        )
        for name in ("SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE", "SECURE_SSL_REDIRECT"):
            self.assertTrue(result[name])
        self.assertFalse(result["USE_X_FORWARDED_HOST"])
        self.assertEqual(result["DATABASES"]["default"]["USER"], "gg_pilot_app")

    def test_rejects_hosts_urls_wildcards_ports_and_invalid_networks(self):
        for changes in (
            {"GG_WIFI_HOST": "*"},
            {"GG_WIFI_HOST": "https://host.test"},
            {"GG_WIFI_HOST": "host.test:8443"},
            {"GG_WIFI_HOST": "127.0.0.1"},
            {"GG_WIFI_HOST": "one..test"},
            {"GG_WIFI_HOST": "-one.test"},
            {"GG_HTTPS_PORT": "80"},
            {"GG_PROXY_IP": "1.1.1.1"},
            {"GG_PROXY_SUBNET": "172.29.86.0/24"},
            {"GG_PROXY_IP": "172.29.87.2"},
            {"GG_APP_IP": "172.29.86.2"},
            {"GG_PROXY_SUBNET": "127.0.0.0/29"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ImproperlyConfigured):
                profile(**changes)

    def test_only_private_proxy_can_assert_https(self):
        factory = RequestFactory()
        middleware = WifiProxyMiddleware(lambda request: HttpResponse("allowed"))
        valid = {
            "REMOTE_ADDR": "172.29.86.2",
            "HTTP_X_FORWARDED_PROTO": "https",
            "HTTP_HOST": "garrafas.wifi.example.invalid:8443",
        }
        with override_settings(
            WIFI_PROXY_ADDRESS="172.29.86.2",
            WIFI_ORIGIN="https://garrafas.wifi.example.invalid:8443",
        ):
            self.assertEqual(middleware(factory.get("/", **valid)).status_code, 200)
            for changes in (
                {"REMOTE_ADDR": "192.168.1.5"},
                {"HTTP_X_FORWARDED_PROTO": "http"},
                {"HTTP_X_FORWARDED_PROTO": "https,http"},
                {"HTTP_HOST": "evil.test"},
            ):
                self.assertEqual(
                    middleware(factory.get("/", **{**valid, **changes})).status_code, 400
                )

    def test_compose_never_shares_existing_volumes_or_mounts_docker_api(self):
        source = (ROOT / "deploy/wifi/compose.yaml").read_text()
        self.assertNotIn("external:", source)
        self.assertNotIn("docker.sock", source)
        self.assertNotIn("2375", source)
        self.assertIn("${GG_BIND_IP:?", source)
        self.assertIn("internal: true", source)

    def test_proxy_requires_device_certificate_crl_and_default_deny(self):
        source = (ROOT / "deploy/wifi/nginx.conf.template").read_text()
        for value in (
            "ssl_verify_client on",
            "ssl_crl ",
            "deny all;",
            "default_server",
            "return 421;",
            "X-Forwarded-Proto https",
            "X-Forwarded-For $remote_addr",
        ):
            self.assertIn(value, source)
        self.assertNotIn("$http_x_forwarded", source)
        self.assertNotIn("$proxy_add_x_forwarded_for", source)


class ConnectionSecurityTests(TestCase):
    def test_status_requires_authentication_and_never_caches(self):
        url = reverse("connection-status")
        self.assertEqual(self.client.get(url).status_code, 302)
        viewer = User.objects.create_user(username="wifi-status-synthetic")
        self.client.force_login(viewer)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(self.client.post(url).status_code, 405)

    @override_settings(
        SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True, SECURE_SSL_REDIRECT=True
    )
    def test_https_login_csrf_and_cookie_flags(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get(reverse("login")).status_code, 301)
        response = client.get(reverse("login"), secure=True)
        self.assertTrue(response.cookies["csrftoken"]["secure"])
        self.assertEqual(client.post(reverse("login"), {}, secure=True).status_code, 403)
        token = response.cookies["csrftoken"].value
        self.assertEqual(
            client.post(
                reverse("login"),
                {},
                secure=True,
                HTTP_X_CSRFTOKEN=token,
                HTTP_ORIGIN="https://evil.invalid",
            ).status_code,
            403,
        )
