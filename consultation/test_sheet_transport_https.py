"""Real PostgreSQL + NGINX mTLS + Chromium. Explicit synthetic CI opt-in only."""

import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from threading import Event
from unittest import skipUnless
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.http import StreamingHttpResponse
from django.test import override_settings
from jwcrypto import jwk
from playwright.sync_api import sync_playwright

from consultation.devices import authorize_device
from consultation.models import AuthorizedDevice, ExportSource, PendingSheet, SheetReceipt
from consultation.signing import signed_snapshot
from inventory.models import Location, Movement, Reference
from native_windows.publisher import render as render_stock
from native_windows.sheet_receiver import render as render_receiver
from scripts.build_vertente import PUBLIC
from tests import browser as existing_browser
from tests.vertente.fixtures import fixture, open_initial_shell, snapshot, wait_offline_shell
from tests.wifi.certificates import certificates
from tests.wifi.tls_device import tls_device
from tests.windows.smoke_stack import free_port

ROOT = Path(__file__).resolve().parents[1]
STOCK = "stock.sheet.playwright"
RECEIVER = "receiver.sheet.playwright"


class LostResponse:
    pause = False
    committed = Event()
    release = Event()

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if self.pause and request.method == "POST" and response.status_code == 200:
            type(self).pause = False
            self.committed.set()
            if not self.release.wait(15):
                raise RuntimeError("Synthetic response-loss synchronization failed")
            # Chromium offline emulation does not reliably close an already-open
            # socket. Actually truncate the response AFTER the real DB commit;
            # the successful signed receipt must never reach the browser.
            def interrupted():
                yield b"{"
                raise ConnectionResetError("Synthetic response interrupted after receipt commit")

            lost = StreamingHttpResponse(interrupted(), content_type="application/json")
            lost["Content-Length"] = "1024"
            return lost
        return response


@skipUnless(
    os.environ.get("RUN_SHEET_TRANSPORT_HTTPS") == "1", "Requires explicit isolated HTTPS CI run"
)
@override_settings(
    ROOT_URLCONF="config.sheet_receiver_urls",
    ALLOWED_HOSTS=[RECEIVER],
    MIDDLEWARE=[
        "config.sheet_receiver_guard.SheetReceiverGuard",
        "consultation.test_sheet_transport_https.LostResponse",
    ],
)
class SheetTransportHTTPSIntegrationTests(StaticLiveServerTestCase):
    database_call = staticmethod(existing_browser.BrowserSmokeTests.database_call)

    def run_command(self, args):
        return subprocess.check_output(
            list(map(str, args)), text=True, stderr=subprocess.PIPE
        ).strip()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gva-sheet-https-")
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.home.chmod(0o755)
        self.key, self.trust = fixture()
        private = self.home / "private"
        private.mkdir(mode=0o700)
        self.signing = private / "signing.pem"
        self.signing.write_bytes(
            self.key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        self.recipient = jwk.JWK.generate(kty="RSA", size=3072)
        (private / "pending-reception.pem").write_bytes(
            self.recipient.export_to_pem(private_key=True, password=None)
        )
        setting = self.settings(VERTENTE_SIGNING_KEY_FILE=str(self.signing))
        setting.enable()
        self.addCleanup(setting.disable)
        ExportSource.objects.create(pk=1, source_id=self.trust["source_id"])
        self.admin = get_user_model().objects.create_user(
            username="synthetic-transport-admin", role="admin"
        )
        self.ref = Reference.objects.create(
            code="TRANSPORT-1",
            name="Água de Ensaio",
            current_stock=12,
            box_capacity=6,
            location=Location.objects.create(name="Local sintético"),
        )
        # The signed stock fixture identifiers must address this fresh DB's real reference.
        self.ref_id = str(self.ref.pk)
        pki = self.home / "pki"
        certificates(pki, STOCK + ",DNS:" + RECEIVER)
        stock_port, receiver_port = free_port(), free_port()
        self.stock_origin = f"https://{STOCK}:{stock_port}"
        self.receiver_origin = f"https://{RECEIVER}:{receiver_port}"
        certificate = x509.load_pem_x509_certificate((pki / "device.crt").read_bytes())
        fingerprint = certificate.fingerprint(hashes.SHA256()).hex()
        self.cfg = {
            "enabled": True,
            "address": "192.168.55.10",
            "clients": ["192.168.55.20/32"],
            "hostname": RECEIVER,
            "port": receiver_port,
            "backend_port": urlsplit(self.live_server_url).port,
            "origin": self.receiver_origin,
            "stock_origin": self.stock_origin,
            "proxy_token": secrets.token_hex(32),
            "devices": {fingerprint: str(uuid.uuid4())},
        }
        fake_root, release = self.home / "data", self.home / "release"
        fake_root.mkdir()
        (fake_root / "installation.json").write_text(
            json.dumps({"db_port": 55432, "http_port": 8765})
        )
        for folder in [fake_root / "tls", fake_root / "secrets/sheet-receiver"]:
            folder.mkdir(parents=True)
            for name in ("server-chain.crt", "server.key", "device-ca.crt", "device-ca.crl"):
                shutil.copyfile(pki / name, folder / name)
                (folder / name).chmod(0o444)
        template = release / "app/deploy/vertente"
        template.mkdir(parents=True)
        shutil.copyfile(
            ROOT / "deploy/vertente/nginx.conf.template", template / "nginx.conf.template"
        )
        for name in [*PUBLIC, "service-worker.js"]:
            dest = release / "app/vertente" / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "vertente" / name, dest)
            dest.chmod(0o644)
        for kind in ("receiver", "publisher"):
            runtime = fake_root / "runtime" / kind
            runtime.mkdir(parents=True)
            runtime.chmod(0o777)
            for child in ("client_body", "proxy", "fastcgi", "scgi", "uwsgi", "client"):
                (runtime / child).mkdir(mode=0o777)
                (runtime / child).chmod(0o777)
        self.policy = signed_snapshot(
            {
                "source_id": self.trust["source_id"],
                "receiver_origin": self.receiver_origin,
                "stock_origin": self.stock_origin,
            },
            self.key,
            kind="vertente-sheet-transport",
            version=1,
        )
        (fake_root / "tls/sheet-transport.public.json").write_text(json.dumps(self.policy))
        stock_cfg = {**self.cfg, "hostname": STOCK, "port": stock_port}
        image = re.search(
            r"image:\s*(\S+)", (ROOT / "deploy/vertente/compose.yaml").read_text()
        ).group(1)
        mounts = [release / "app/vertente", fake_root / "tls", fake_root / "secrets/sheet-receiver"]
        for kind, config in [
            ("publisher", render_stock(release, fake_root, stock_cfg)),
            ("receiver", render_receiver(fake_root, release, self.cfg)),
        ]:
            config = config.replace("192.168.55.10:", "127.0.0.1:").replace(
                "allow 192.168.55.20/32;", "allow 127.0.0.1;"
            )
            config = config.replace(
                'include "' + (release / "nginx/conf/mime.types").as_posix() + '";',
                "include /etc/nginx/mime.types;",
            )
            path = self.home / (kind + ".conf")
            path.write_text(config)
            path.chmod(0o444)
            name = "gva-sheet-test-" + uuid.uuid4().hex
            command = [
                "docker",
                "run",
                "--detach",
                "--name",
                name,
                "--network",
                "host",
                "--read-only",
                "--user",
                "101:101",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=32m",
                "--entrypoint",
                "nginx",
                "-v",
                f"{path}:/etc/nginx/nginx.conf:ro",
                "-v",
                f"{fake_root / 'runtime' / kind}:{fake_root / 'runtime' / kind}:rw",
            ]
            for folder in mounts:
                command += ["-v", f"{folder}:{folder}:ro"]
            self.run_command([*command, image, "-g", "daemon off;"])
            self.addCleanup(
                lambda name=name: subprocess.run(
                    ["docker", "rm", "-f", name], capture_output=True, check=True
                )
            )
        # Trust is scoped to this disposable browser home, not the host trust store.
        browser_home = self.home / "browser-home"
        nss = browser_home / ".pki/nssdb"
        nss.mkdir(parents=True)
        self.run_command(["certutil", "-N", "--empty-password", "-d", "sql:" + str(nss)])
        self.run_command(
            [
                "certutil",
                "-A",
                "-n",
                "Synthetic transport CA",
                "-t",
                "C,,",
                "-i",
                pki / "ca.crt",
                "-d",
                "sql:" + str(nss),
            ]
        )
        for host, port in [(STOCK, stock_port), (RECEIVER, receiver_port)]:
            adapter = tls_device(pki, host, port)
            adapter.__enter__()
            self.addCleanup(adapter.__exit__, None, None, None)
        self.override = self.settings(SHEET_RECEIVER=self.cfg)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.pw = sync_playwright().start()
        self.addCleanup(self.pw.stop)
        self.context = self.pw.chromium.launch_persistent_context(
            str(self.home / "profile"),
            executable_path=os.getenv("CHROMIUM_PATH") or shutil.which("chromium"),
            headless=True,
            args=[
                "--no-sandbox",
                f"--host-resolver-rules=MAP {STOCK} 127.0.0.2,MAP {RECEIVER} 127.0.0.2",
                "--no-proxy-server",
            ],
            env={**os.environ, "HOME": str(browser_home)},
            viewport={"width": 393, "height": 851},
            is_mobile=True,
            has_touch=True,
        )
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(12000)
        open_initial_shell(self.page, self.stock_origin)
        self.page.locator("#trust-file").wait_for()
        self.page.evaluate(
            "async t=>{const s=await import('/assets/store.js');await s.enroll(t,t.keys[0].key_id);}",
            self.trust,
        )
        self.request = self.call("deviceRequest")
        self.cfg["devices"][fingerprint] = self.request["device_id"]
        auth = self.database_call(
            lambda: authorize_device(
                self.request, role="employee", allow_import=True, allow_sheets=True
            )
        )
        self.call("activate", auth)
        refs = [
            {
                "id": self.ref_id,
                "name": "Água de Ensaio",
                "bottles": 12,
                "box_capacity": 6,
                "location": "Local sintético",
                "sector": None,
                "minimum": None,
            }
        ]
        self.call("importSnapshot", snapshot(self.key, self.trust, references=refs))
        # Export the exact capability through the production command.
        from django.core.management import call_command

        permission_file = private / "permission.json"
        self.database_call(
            lambda: call_command(
                "pending_sheet_authorize",
                device=self.request["device_id"],
                output=str(permission_file),
            )
        )
        recipient = signed_snapshot(
            {
                "source_id": self.trust["source_id"],
                "jwk": json.loads(self.recipient.export_public()),
                "key_id": self.recipient.thumbprint(),
            },
            self.key,
            kind="vertente-sheet-recipient",
            version=1,
        )
        self.sheets("configureSheets", "permission", json.loads(permission_file.read_text()))
        self.sheets("configureSheets", "recipient", recipient)
        self.sheets("unlockSheets", "Synthetic-sheet-only-private-phrase")
        self.sheets("configureTransport", self.policy, True)

    def call(self, method, *args):
        return self.page.evaluate(
            "async a=>(await import('/assets/store.js'))[a.method](...a.args)",
            {"method": method, "args": args},
        )

    def sheets(self, method, *args):
        return self.page.evaluate(
            "async a=>(await import('/assets/sheets.js'))[a.method](...a.args)",
            {"method": method, "args": args},
        )

    def prepared(self):
        id = self.sheets("createSheet", "entry")
        self.sheets(
            "editSheet",
            id,
            1,
            {
                "person": "Pessoa fictícia transportada",
                "physical_date": "2026-10-01",
                "notes": "Folha sintética",
                "lines": [{"reference_id": self.ref_id, "boxes": 1, "units": 2}],
            },
        )
        self.sheets("exportSheet", id, 2)
        return id

    def test_real_https_mtls_lost_response_retry_offline_revocation_and_optional_stage31(self):
        id = self.prepared()
        LostResponse.committed.clear()
        LostResponse.release.clear()
        LostResponse.pause = True
        self.page.evaluate(
            "id=>{window.delivery=(import('/assets/sheets.js').then(m=>m.sendSheet(id,2))).then(()=>true,()=>false);}",
            id,
        )
        try:
            self.assertTrue(
                LostResponse.committed.wait(12),
                "Receiver did not commit before synthetic network loss",
            )
            self.context.set_offline(True)
        finally:
            LostResponse.release.set()
        self.assertFalse(self.page.evaluate("async()=>await window.delivery"))
        self.assertEqual(self.database_call(lambda: PendingSheet.objects.count()), 1)
        self.assertEqual(self.sheets("sheetState")["deliveries"][id]["state"], "failure")
        self.context.set_offline(False)
        self.sheets("sendSheet", id, 2)
        self.assertEqual(self.sheets("sheetState")["deliveries"][id]["state"], "duplicate")
        self.assertEqual(self.database_call(lambda: SheetReceipt.objects.count()), 2)
        self.assertEqual(
            self.database_call(lambda: Reference.objects.get(pk=self.ref.pk).current_stock), 12
        )
        self.assertEqual(self.database_call(lambda: Movement.objects.count()), 0)
        wait_offline_shell(self.page)
        self.context.set_offline(True)
        self.page.reload()
        self.page.get_by_role("heading", name="Última atualização de stock", exact=True).wait_for()
        self.sheets("unlockSheets", "Synthetic-sheet-only-private-phrase")
        self.assertEqual(self.sheets("sheetState")["deliveries"][id]["state"], "duplicate")
        self.context.set_offline(False)
        second = self.prepared()
        self.database_call(
            lambda: AuthorizedDevice.objects.filter(pk=self.request["device_id"]).update(
                sheets_allowed=False
            )
        )
        with self.assertRaises(Exception):
            self.sheets("sendSheet", second, 2)
        self.assertEqual(self.database_call(lambda: PendingSheet.objects.count()), 1)
        self.assertEqual(self.context.cookies(), [])
        # Only this explicitly selected temporary composition may load PR #31.
        from django.apps import apps

        if apps.all_models["consultation"].get("sheetaction"):

            def administrative_confirmation():
                from consultation.review import confirm_sheet, review_sheet

                sheet = PendingSheet.objects.get()
                review, _ = review_sheet(sheet.pk, actor=self.admin, sequence=0)
                args = dict(
                    actor=self.admin,
                    sequence=review.sequence,
                    token=review.data["token"],
                    confirmed=True,
                    report_requested=False,
                )
                first = confirm_sheet(sheet.pk, **args)
                second = confirm_sheet(sheet.pk, **args)
                return first.pk, second.pk

            first, repeated = self.database_call(administrative_confirmation)
            self.assertEqual(first, repeated)
            self.assertEqual(
                self.database_call(lambda: Reference.objects.get(pk=self.ref.pk).current_stock), 20
            )
            self.assertEqual(self.database_call(lambda: Movement.objects.count()), 1)
