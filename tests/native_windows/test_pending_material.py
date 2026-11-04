import base64
import json
import tempfile
from pathlib import Path
from unittest import TestCase

from jwcrypto import jwk

from native_windows.maintenance import validate_pending_material
from native_windows.package import UnsafeOperation


class PendingMaterialTests(TestCase):
    def test_old_installation_without_pending_sheets_does_not_require_a_new_key(self):
        with tempfile.TemporaryDirectory() as directory:
            validate_pending_material(directory, needed=False)
            with self.assertRaises(UnsafeOperation):
                validate_pending_material(directory, needed=True)

    def test_matching_key_is_required_before_backup_can_be_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "signing").mkdir()
            key = jwk.JWK.generate(kty="RSA", size=3072)
            path = root / "signing/pending-reception.pem"
            path.write_bytes(key.export_to_pem(private_key=True, password=None))
            public = path.with_suffix(".public.json")
            public.write_text(
                json.dumps(
                    {
                        "payload": base64.urlsafe_b64encode(
                            json.dumps({"key_id": key.thumbprint()}).encode()
                        )
                        .decode()
                        .rstrip("=")
                    }
                )
            )
            validate_pending_material(root, needed=True)
            public.write_text(
                json.dumps(
                    {
                        "payload": base64.urlsafe_b64encode(b'{"key_id":"wrong"}')
                        .decode()
                        .rstrip("=")
                    }
                )
            )
            with self.assertRaises(UnsafeOperation):
                validate_pending_material(root, needed=True)
