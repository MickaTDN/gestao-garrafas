"""Exports using the actual restricted DB role in a NEW synthetic pilot."""

import json
import tempfile
from pathlib import Path

from tests.windows.smoke_stack import free_port, make_state, run


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
from consultation.models import ExportSource
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
            print(
                "PASS Vertente export: restricted application role, private local key, stable source/counter, full signed zero/unknown-capacity snapshot, unchanged stock and no movements/import batches",
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
