"""Durable maintenance journal. A failed migration never re-enables older code."""

import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path

from .package import UnsafeOperation


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".new")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


@contextmanager
def exclusive(root):
    """OS lock is released after crashes; the durable journal remains fail-closed."""
    path = Path(root) / "maintenance.lock"
    with path.open("a+b") as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise UnsafeOperation("Já existe uma instalação ou manutenção em curso.") from error
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def update(root, manifest, actions):
    """Injected OS/DB boundary permits fault tests at every transition."""
    root = Path(root)
    journal = root / "maintenance.json"
    with exclusive(root):
        if journal.exists():
            raise UnsafeOperation(
                "Manutenção interrompida: é necessário recuperar com a informática."
            )
        previous = json.loads((root / "installation.json").read_text())
        record = {
            "schema": 1,
            "id": str(uuid.uuid4()),
            "from": previous["version"],
            "to": manifest["version"],
            "phase": "prepared",
        }
        write_json(journal, record)
        try:
            # Disables service autostart BEFORE any migration. Reboot cannot start old code.
            for phase, operation in (
                ("services-disabled", actions.disable),
                ("services-stopped", actions.stop),
                ("backup-restored-and-verified", actions.backup_and_restore_check),
                ("migrated", actions.migrate),
                ("health-verified", actions.health),
            ):
                operation()
                record["phase"] = phase
                write_json(journal, record)
            # Activation is the final commit point; same data root and identity.
            next_state = {
                **previous,
                "version": manifest["version"],
                "release": str(actions.release),
            }
            write_json(root / "installation.json", next_state)
            actions.activate()
            record["phase"] = "completed"
            write_json(root / ("update-" + record["id"] + ".json"), record)
            journal.unlink()
        except Exception:
            # Even if activate partly succeeded, stop and disable everything again.
            try:
                actions.disable()
                actions.stop()
            finally:
                record["failed"] = True
                write_json(journal, record)
            raise
