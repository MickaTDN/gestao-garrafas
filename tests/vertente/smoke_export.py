"""Exports using the actual restricted DB role in a NEW synthetic pilot."""

import hashlib
import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from consultation.signing import b64
from tests.windows.smoke_stack import ROOT, free_port, make_state, run


def main(image, *, preserve_volumes=False):
    command = None
    with tempfile.TemporaryDirectory(prefix="gg-va7-export-") as temporary:
        try:
            _, _, candidate = make_state(Path(temporary) / "pilot", image, free_port())
            command = candidate
            run(command + ["up", "-d", "--wait", "db"])
            run(command + ["--profile", "setup", "run", "--rm", "initialize"])
            run(command + ["up", "-d", "--wait", "--wait-timeout", "180", "app"])
            run(
                command
                + [
                    "exec",
                    "-T",
                    "app",
                    "python",
                    "manage.py",
                    "vertente_setup",
                    "--directory",
                    "/tmp/va-signing",
                ]
            )
            code = """
from accounts.models import User
from consultation.exports import export_snapshot
from consultation.models import AuthorizedDevice, ExportSource
from django.db import ProgrammingError, transaction
import uuid
from inventory.models import Reference, Movement, ImportBatch
from django.db import connection
import base64, json
assert connection.settings_dict['USER']=='gg_pilot_app'
actor=User.objects.create_user(username='va-synthetic-consultation',role='viewer')
before=list(Reference.objects.order_by('pk').values_list('pk','current_stock','stock_version'))
first=export_snapshot(actor=actor)
second=export_snapshot(actor=actor)
data=json.loads(base64.urlsafe_b64decode(second['payload']+'=='))
assert data['sequence']==2 and len(data['references'])==3
assert any(row['bottles']==0 for row in data['references'])
assert any(row['box_capacity'] is None for row in data['references'])
assert before==list(Reference.objects.order_by('pk').values_list('pk','current_stock','stock_version'))
assert not Movement.objects.exists() and not ImportBatch.objects.exists()
try:
    with transaction.atomic():
        AuthorizedDevice.objects.create(device_id=uuid.uuid4(),public_key_id='0'*64,role='owner')
except ProgrammingError:
    pass
else:
    raise AssertionError('Web role must not issue offline device authorizations')
print(json.dumps({'sequence':data['sequence'],'references':len(data['references'])}))
"""
            output = run(
                command
                + [
                    "exec",
                    "-T",
                    "-e",
                    "VERTENTE_SIGNING_KEY_FILE=/tmp/va-signing/signing.pem",
                    "app",
                    "python",
                    "manage.py",
                    "shell",
                    "-c",
                    code,
                ]
            )
            assert json.loads(output.splitlines()[-1]) == {"sequence": 2, "references": 3}
            # Actual owner/setup service uses the SAME reviewed secret overlay;
            # the web role above was explicitly unable to issue a grant.
            key_file = Path(temporary) / "private-signing.pem"
            # Docker archive/cp cannot read this engine's tmpfs mount. Transfer
            # only the NEW synthetic test key straight to a private file, never logs.
            with key_file.open("xb") as output:
                key_file.chmod(0o600)
                subprocess.run(
                    command
                    + [
                        "exec",
                        "-T",
                        "app",
                        "python",
                        "-c",
                        "import sys;from pathlib import Path;sys.stdout.buffer.write(Path('/tmp/va-signing/signing.pem').read_bytes())",
                    ],
                    stdout=output,
                    stderr=subprocess.PIPE,
                    check=True,
                    timeout=30,
                )
            key_file.chmod(0o444)  # Parent is 0700; read-only Docker secret for UID 10001.
            device_key = ec.generate_private_key(ec.SECP256R1())
            device_id = str(uuid.uuid4())
            der = device_key.public_key().public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            r, s = decode_dss_signature(
                device_key.sign(
                    ("vertente-device-request-v1\0" + device_id).encode(), ec.ECDSA(hashes.SHA256())
                )
            )
            request = {
                "format": "vertente-device-request",
                "version": 1,
                "device_id": device_id,
                "spki": b64(der),
                "signature": b64(r.to_bytes(32, "big") + s.to_bytes(32, "big")),
            }
            fingerprint = hashlib.sha256(der).hexdigest()
            owner_code = """
import io,json,os
from pathlib import Path
from django.core.management import call_command
from django.db import connection
from consultation.models import AuthorizedDevice
from inventory.models import Reference,Movement,ImportBatch
stock_before=list(Reference.objects.order_by('pk').values_list('pk','current_stock','stock_version'))
assert connection.settings_dict['USER']=='gg_pilot_owner'
root=Path('/tmp/device-provision');root.mkdir(mode=0o700)
request=REQUEST_PLACEHOLDER
(root/'request.json').write_text(json.dumps(request))
call_command('vertente_device',request=str(root/'request.json'),output=str(root/'grant.json'),role='employee',confirmed_device_fingerprint=FINGERPRINT_PLACEHOLDER,stdout=io.StringIO())
file=json.loads((root/'grant.json').read_text())
assert file['format']=='vertente-device' and file['version']==1
assert AuthorizedDevice.objects.get(device_id=request['device_id']).role=='employee'
assert list(Reference.objects.order_by('pk').values_list('pk','current_stock','stock_version'))==stock_before
assert not Movement.objects.exists() and not ImportBatch.objects.exists()
print('PASS read-only signing overlay available to separate owner provisioning; web role denied device writes')
""".replace("REQUEST_PLACEHOLDER", repr(request)).replace(
                "FINGERPRINT_PLACEHOLDER", repr(fingerprint)
            )
            overlay = command + ["--file", str(ROOT / "deploy/vertente/export.compose.yaml")]
            environment = {**os.environ, "VA_SIGNING_KEY_FILE": str(key_file)}
            output = run(
                overlay
                + [
                    "--profile",
                    "setup",
                    "run",
                    "--rm",
                    "--no-deps",
                    "initialize",
                    "python",
                    "manage.py",
                    "shell",
                    "-c",
                    owner_code,
                ],
                env=environment,
            )
            assert "PASS read-only signing overlay" in output
            print(
                "PASS Vertente export: restricted application role, separate owner provisioning with signing overlay, private local key, stable source/counter, full signed zero/unknown-capacity snapshot, unchanged stock and no movements/import batches",
                flush=True,
            )
        finally:
            if command:
                run(
                    command
                    + ["down", "--remove-orphans"]
                    + ([] if preserve_volumes else ["--volumes"])
                )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--preserve-volumes", action="store_true")
    args = parser.parse_args()
    main(args.image, preserve_volumes=args.preserve_volumes)
