"""Real receiver service/mTLS/receipt preservation on a disposable Windows runner."""

import base64
import hashlib
import http.client
import ipaddress
import json
import os
import socket
import ssl
import uuid
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from jwcrypto import jwe, jwk


def main(root, directory):
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.name != "nt":
        raise RuntimeError("Disposable Windows CI only")
    from consultation.signing import public_key, signed_snapshot
    from native_windows.maintenance import connection
    from native_windows.runtime import manage
    from native_windows.sheet_receiver import approved, control, setup
    from tests.wifi.certificates import certificates

    root = Path(root)
    address = next(
        v
        for v in socket.gethostbyname_ex(socket.gethostname())[2]
        if any(
            ipaddress.ip_address(v) in ipaddress.ip_network(n)
            for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
        )
    )
    pki = Path(directory) / "receiver-test-pki"
    hostname = "sheets.synthetic.test"
    certificates(pki, hostname)
    key = ec.generate_private_key(ec.SECP256R1())
    public = public_key(key)
    device = str(uuid.uuid4())
    fingerprint = (
        x509.load_pem_x509_certificate((pki / "device.crt").read_bytes())
        .fingerprint(hashes.SHA256())
        .hex()
    )
    manage(
        root,
        "shell",
        "-c",
        "from consultation.models import AuthorizedDevice;from django.utils import timezone;from datetime import timedelta;"
        + "AuthorizedDevice.objects.create(device_id="
        + repr(device)
        + ",public_key_id="
        + repr(public["key_id"])
        + ",public_spki="
        + repr(public["spki"])
        + ",role='employee',revision=1,sheets_allowed=True,expires_at=timezone.now()+timedelta(days=1))",
    )
    with connection(root) as conn:
        source = conn.execute(
            "SELECT source_id::text FROM consultation_exportsource WHERE id=1"
        ).fetchone()[0]
        ref, capacity = conn.execute(
            "SELECT id::text,box_capacity FROM inventory_reference ORDER BY code LIMIT 1"
        ).fetchone()
    payload = {
        "source_id": source,
        "device_id": device,
        "authorization_revision": 1,
        "sheet_id": str(uuid.uuid4()),
        "revision": 1,
        "kind": "entry",
        "physical_date": "2026-01-02",
        "person": "Pessoa fictícia Wi-Fi",
        "notes": "Synthetic transport only",
        "lines": [{"reference_id": ref, "boxes": 0, "units": 2, "box_capacity": capacity}],
    }
    recipient = jwk.JWK.from_pem((root / "signing/pending-reception.pem").read_bytes())
    encrypted = jwe.JWE(
        json.dumps(signed_snapshot(payload, key, kind="vertente-sheet", version=1)).encode(),
        protected={"alg": "RSA-OAEP-256", "enc": "A256GCM", "kid": recipient.thumbprint()},
        recipient=recipient.public(),
    )
    raw = json.dumps(
        {"format": "vertente-pending-sheet", "version": 1, "jwe": encrypted.serialize(compact=True)}
    ).encode()
    configuration = pki / "config.json"
    configuration.write_text(
        json.dumps(
            {
                "it_approved": True,
                "address": address,
                "hostname": hostname,
                "port": 8446,
                "backend_port": 8767,
                "stock_origin": "https://stock.synthetic.test:8444",
                "clients": [address + "/32"],
                "devices": {fingerprint: device},
            }
        )
    )
    setup(root, {"configuration": str(configuration)})
    assert not approved(root)
    control(root, {"enable": True, "it_network_ready": True})

    def request(certificate, data=raw, path="/v1/pending-sheets"):
        nonce = str(uuid.uuid4())
        context = ssl.create_default_context(cafile=str(pki / "ca.crt"))
        if certificate:
            context.load_cert_chain(pki / (certificate + ".crt"), pki / (certificate + ".key"))
        with socket.create_connection((address, 8446), timeout=10) as plain:
            with context.wrap_socket(plain, server_hostname=hostname) as secure:
                secure.sendall(
                    (
                        f"POST {path} HTTP/1.1\r\nHost: {hostname}:8446\r\nOrigin: https://stock.synthetic.test:8444\r\n"
                        f"Content-Type: application/json\r\nX-GVA-Request: {nonce}\r\nContent-Length: {len(data)}\r\nConnection: close\r\n\r\n"
                    ).encode()
                    + data
                )
                response = http.client.HTTPResponse(secure)
                response.begin()
                return response.status, response.read(), nonce

    signing = serialization.load_pem_private_key(
        (root / "signing/signing.pem").read_bytes(), password=None
    )
    try:
        for outcome in ("pending", "duplicate"):
            status, body, nonce = request("device")
            assert status == 200, "Synthetic receiver HTTP status=" + str(status)
            envelope = json.loads(body)
            plain = base64.urlsafe_b64decode(envelope["payload"] + "==")
            signature = base64.urlsafe_b64decode(envelope["signature"] + "==")
            signing.public_key().verify(
                encode_dss_signature(
                    int.from_bytes(signature[:32]), int.from_bytes(signature[32:])
                ),
                b"vertente-sheet-receipt-v1\0" + plain,
                ec.ECDSA(hashes.SHA256()),
            )
            proof = json.loads(plain)
            assert (proof["outcome"], proof["request_id"], proof["file_sha256"]) == (
                outcome,
                nonce,
                hashlib.sha256(raw).hexdigest(),
            )
        for certificate in (None, "revoked"):
            try:
                assert request(certificate)[0] != 200
            except (ssl.SSLError, ConnectionError):
                pass
        assert request("device", path="/admin/")[0] == 404
        assert request("device", data=b"{}")[0] == 400
        manage(
            root,
            "shell",
            "-c",
            "from consultation.models import AuthorizedDevice;AuthorizedDevice.objects.filter(pk="
            + repr(device)
            + ").update(sheets_allowed=False)",
        )
        assert request("device")[0] != 200
        with connection(root) as conn:
            assert (
                conn.execute("SELECT sum(current_stock) FROM inventory_reference").fetchone()[0]
                == 33
            )
            assert (
                conn.execute(
                    "SELECT count(*) FROM consultation_sheetreceipt WHERE actor_id IS NULL"
                ).fetchone()[0]
                == 2
            )
    finally:
        control(root, {"enable": False})
    assert not approved(root)
    print(
        "PASS: native receiver mTLS, signed receipts, idempotence, revocation, no stock effect; disabled after test."
    )
