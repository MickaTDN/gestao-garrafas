"""Before/after assertions for a real reboot by an authorized disposable VM runner.

Never reboots a computer itself. An external approved VM orchestrator performs
that step and resumes `after`. Rejects physical machines, Server and real data.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main(phase):
    if os.name != "nt" or os.environ.get("GVA_DISPOSABLE_VM_APPROVED") != "1":
        raise RuntimeError("Explicitly approved disposable Windows11 VM only")
    machine = json.loads(
        subprocess.check_output(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$c=Get-CimInstance Win32_ComputerSystem;$o=Get-CimInstance Win32_OperatingSystem;@{model=$c.Model;manufacturer=$c.Manufacturer;type=$o.ProductType;build=$o.BuildNumber}|ConvertTo-Json -Compress",
            ],
            text=True,
        )
    )
    if (
        machine["model"] != "Virtual Machine"
        or machine["manufacturer"] != "Microsoft Corporation"
        or machine["type"] != 1
        or int(machine["build"]) < 22000
    ):
        raise RuntimeError("Only an isolated Hyper-V Windows11 guest is accepted")
    os.environ["GVA_NATIVE_CHANNEL"] = "synthetic"
    from native_windows.cli import data_root
    from native_windows.maintenance import connection, evidence, matching_evidence
    from native_windows.package import digest
    from native_windows.state import write_json
    from native_windows.windows import SERVICES, service_state

    root = data_root()
    state = json.loads((root / "installation.json").read_text())
    if (
        state["channel"] != "synthetic"
        or state["database"] != "gva_native_synthetic"
        or (root / "maintenance.json").exists()
    ):
        raise RuntimeError("Healthy synthetic installation required")
    proof = root / "backups/reboot-proof.json"
    if phase == "before":
        with connection(root) as conn:
            if (
                conn.execute("SELECT count(*) FROM inventory_importbatch").fetchone()[0]
                or conn.execute(
                    "SELECT count(*) FROM inventory_reference WHERE code NOT LIKE 'SYN-C-%'"
                ).fetchone()[0]
                or not conn.execute(
                    "SELECT count(*) FROM inventory_movement WHERE status='confirmed'"
                ).fetchone()[0]
            ):
                raise RuntimeError(
                    "Prepared synthetic confirmed movements required; imported data refused"
                )
            value = {
                "instance": state["instance"],
                "evidence": evidence(conn),
                "signing": digest(root / "signing/signing.pem"),
            }
        if proof.exists():
            raise RuntimeError("Existing reboot proof is never overwritten")
        write_json(proof, value)
        print(
            "PASS before: proof preserved. The approved VM orchestrator must now reboot this guest."
        )
    elif phase == "after":
        previous = json.loads(proof.read_text())
        for _ in range(120):
            if all(service_state(SERVICES[kind]) == 4 for kind in ("postgres", "web", "backup")):
                break
            time.sleep(1)
        else:
            raise RuntimeError("Native services did not restart")
        with connection(root) as conn:
            assert matching_evidence(evidence(conn), previous["evidence"])
        assert previous["instance"] == state["instance"]
        assert previous["signing"] == digest(root / "signing/signing.pem")
        from native_windows.install import health_http

        health_http(root)
        print(
            "PASS after: confirmed data, documents, identities, keys and services survived the real VM reboot."
        )
    else:
        raise RuntimeError("Choose before or after")


if __name__ == "__main__":
    main(sys.argv[1])
