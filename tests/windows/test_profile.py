import os
import runpy
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]
ENV = {
    "APP_ENV": "windows-local",
    "GG_WINDOWS_PILOT": "synthetic-v1",
    "DB_ENGINE": "postgresql",
    "DB_HOST": "db",
    "DB_NAME": "garrafas_windows_synthetic",
    "GG_BOOTSTRAP_OWNER": "0",
}


def profile(**changes):
    with (
        patch.dict(os.environ, {**ENV, **changes}),
        patch("pathlib.Path.read_text", return_value="synthetic-local-key-not-a-credential"),
    ):
        return runpy.run_module("config.windows_local")


class WindowsProfileTests(SimpleTestCase):
    def test_requires_explicit_pilot_and_nonproduction_environment(self):
        for changes in ({"GG_WINDOWS_PILOT": ""}, {"APP_ENV": "production"}):
            with self.subTest(changes=changes), self.assertRaises(ImproperlyConfigured):
                profile(**changes)

    def test_refuses_reserved_or_external_database_targets(self):
        for changes in (
            {"DB_NAME": "garrafas"},
            {"DB_HOST": "127.0.0.1"},
            {"DB_HOST": "example.invalid"},
            {"DB_ENGINE": "sqlite"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ImproperlyConfigured):
                profile(**changes)

    def test_loopback_only_hosts_and_no_trusted_proxy_or_wifi_origins(self):
        settings = profile(DJANGO_ALLOWED_HOSTS="*", TRUST_HTTPS_PROXY="1")
        self.assertEqual(settings["ALLOWED_HOSTS"], ["127.0.0.1", "localhost"])
        self.assertEqual(settings["CSRF_TRUSTED_ORIGINS"], [])
        self.assertIsNone(settings["SECURE_PROXY_SSL_HEADER"])
        self.assertEqual(settings["LOGIN_TRUSTED_PROXY_ADDRESSES"], set())
        self.assertFalse(settings["DEBUG"])

    def test_uses_application_role_and_file_secrets(self):
        settings = profile()
        self.assertEqual(settings["DATABASES"]["default"]["USER"], "gg_pilot_app")
        self.assertEqual(settings["DATABASES"]["default"]["HOST"], "db")
        self.assertEqual(settings["DATABASES"]["default"]["NAME"], "garrafas_windows_synthetic")
        self.assertEqual(settings["SECRET_KEY"], "synthetic-local-key-not-a-credential")

    def test_owner_is_only_selected_for_explicit_bootstrap_process(self):
        self.assertEqual(
            profile(GG_BOOTSTRAP_OWNER="1")["DATABASES"]["default"]["USER"], "gg_pilot_owner"
        )
        self.assertEqual(
            profile(GG_BOOTSTRAP_OWNER="anything")["DATABASES"]["default"]["USER"], "gg_pilot_app"
        )

    def test_cookies_http_exception_is_limited_to_explicit_loopback_profile(self):
        settings = profile()
        self.assertFalse(settings["SESSION_COOKIE_SECURE"])
        self.assertFalse(settings["CSRF_COOKIE_SECURE"])
        self.assertFalse(settings["SECURE_SSL_REDIRECT"])
        self.assertEqual(settings["SECURE_HSTS_SECONDS"], 0)
        self.assertEqual(
            settings["STORAGES"]["staticfiles"]["BACKEND"],
            "whitenoise.storage.CompressedManifestStaticFilesStorage",
        )

    def test_user_scripts_do_not_contain_destructive_or_privilege_bypass_commands(self):
        for path in (ROOT / "scripts/windows").glob("*"):
            source = path.read_text().lower()
            self.assertNotIn("executionpolicy", source)
            self.assertNotIn("-verb runas", source)
            self.assertNotIn("new-netfirewallrule", source)
            self.assertNotIn("--volumes", source)
            self.assertNotIn("system prune", source)

    def test_compose_has_fixed_loopback_and_no_external_volume_adoption(self):
        source = (ROOT / "deploy/windows/compose.yaml").read_text()
        self.assertIn('"127.0.0.1:${GG_HTTP_PORT:-8765}:8000"', source)
        self.assertNotIn("external:", source)
        self.assertIn("internal: true", source)
        self.assertNotIn("/var/run/docker.sock", source)
