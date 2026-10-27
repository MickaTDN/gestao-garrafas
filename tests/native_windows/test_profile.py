import json
import os
import runpy
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured

from native_windows.publisher import render

ROOT = Path(__file__).resolve().parents[2]


class NativeProfileTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "secrets").mkdir()
        self.state = {
            "schema": 1,
            "postgres_major": 17,
            "database": "gva_native_synthetic",
            "db_port": 55432,
        }
        (self.root / "installation.json").write_text(json.dumps(self.state))
        for role in ("owner", "app"):
            (self.root / f"secrets/{role}.json").write_text(
                json.dumps(
                    {
                        "username": role,
                        "password": "synthetic-not-a-credential",
                        "django_key": "synthetic-not-a-secret",
                    }
                )
            )

    def profile(self, **changes):
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "windows-native",
                "GVA_DATA_ROOT": str(self.root),
                "GVA_MAINTENANCE": "0",
                **changes,
            },
        ):
            return runpy.run_module("config.windows_native")

    def test_explicit_profile_and_new_native_database_marker_only(self):
        with self.assertRaises(ImproperlyConfigured):
            self.profile(APP_ENV="development")
        for database in ("garrafas", "garrafas_windows_synthetic", "reserved-import-preview"):
            (self.root / "installation.json").write_text(
                json.dumps({**self.state, "database": database})
            )
            with self.subTest(database=database), self.assertRaises(ImproperlyConfigured):
                self.profile()

    def test_environment_cannot_expose_django_or_adopt_other_database(self):
        profile = self.profile(
            DB_HOST="example.invalid",
            DB_NAME="reserved",
            DJANGO_DEBUG="1",
            DJANGO_ALLOWED_HOSTS="*",
            TRUST_HTTPS_PROXY="1",
        )
        self.assertFalse(profile["DEBUG"])
        self.assertEqual(profile["DATABASES"]["default"]["HOST"], "127.0.0.1")
        self.assertEqual(profile["DATABASES"]["default"]["NAME"], "gva_native_synthetic")
        self.assertEqual(profile["DATABASES"]["default"]["USER"], "app")
        self.assertEqual(profile["ALLOWED_HOSTS"], ["127.0.0.1", "localhost"])
        self.assertEqual(profile["CSRF_TRUSTED_ORIGINS"], [])
        self.assertIsNone(profile["SECURE_PROXY_SSL_HEADER"])
        self.assertEqual(profile["LOGIN_TRUSTED_PROXY_ADDRESSES"], set())

    def test_owner_only_explicit_maintenance_and_signing_outside_program(self):
        self.assertEqual(self.profile(GVA_MAINTENANCE="1")["DATABASES"]["default"]["USER"], "owner")
        self.assertEqual(
            Path(self.profile()["VERTENTE_SIGNING_KEY_FILE"]), self.root / "signing/signing.pem"
        )


class NativePublisherTests(TestCase):
    def setUp(self):
        import shutil

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.release = Path(self.tmp.name)
        directory = self.release / "app/deploy/vertente"
        directory.mkdir(parents=True)
        shutil.copy2(
            ROOT / "deploy/vertente/nginx.conf.template", directory / "nginx.conf.template"
        )

    def config(self, **changes):
        return {
            "address": "192.168.10.20",
            "hostname": "stock.example.internal",
            "clients": ["192.168.10.30/32"],
            "port": 8444,
            **changes,
        }

    def test_reuses_entire_mtls_crl_and_content_policy_without_backend(self):
        text = render(self.release, Path("/private-native"), self.config())
        for item in (
            "ssl_verify_client on",
            "ssl_crl",
            "TLSv1.2 TLSv1.3",
            "deny all",
            "192.168.10.20:8444",
            "allow 192.168.10.30/32",
            "form-action 'none'",
            "limit_except GET",
            "return 404",
            "vertente",
        ):
            self.assertIn(item, text)
        self.assertNotIn("proxy_pass", text)
        self.assertNotIn("/run/tls", text)
        self.assertNotIn("listen 8444", text)
        self.assertNotIn("/etc/nginx", text)

    def test_rejects_public_wildcard_and_injected_network_configuration(self):
        from native_windows.package import UnsafeOperation

        for config in (
            self.config(address="0.0.0.0"),
            self.config(address="8.8.8.8"),
            self.config(hostname="stock;include evil"),
            self.config(clients=["0.0.0.0/0"]),
            self.config(clients=[]),
            self.config(port=443),
            self.config(clients=["192.168.0.1/24"]),
        ):
            with self.subTest(config=config), self.assertRaises((UnsafeOperation, ValueError)):
                render(self.release, Path("/private-native"), config)
