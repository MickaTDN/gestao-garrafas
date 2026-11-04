"""Admin-only portable backup export. No browser-controlled filesystem access."""

import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from .crypto_backup import decrypt
from .maintenance import backup, restore_check
from .package import UnsafeOperation, digest, refuse_reparse
from .portable import envelope, material, unlock
from .runtime import manage, read_state
from .state import exclusive, write_json
from .windows import administrator, protect


def external_destination(root, value):
    root = Path(root).resolve()
    target = Path(value)
    refuse_reparse(target)
    target = target.resolve()
    state = read_state(root)
    program = Path(state["release"]).resolve().parent.parent.parent
    if (
        not target.is_absolute()
        or target.suffix.lower() != ".gvabackup"
        or target.exists()
        or not target.parent.is_dir()
        or root == target
        or root in target.parents
        or program == target
        or program in target.parents
    ):
        raise UnsafeOperation(
            "Escolha um ficheiro .gvabackup NOVO fora das pastas do programa e dos dados."
        )
    return target


def export_backup(root, request):
    administrator()
    root = Path(root)
    target = external_destination(root, request["destination"])
    with exclusive(root):
        if (root / "maintenance.json").exists():
            raise UnsafeOperation("Há manutenção pendente; cópia manual recusada.")
        state = read_state(root)
        config_path = root / "secrets/recovery-envelope.json"
        password = request.get("portable_password", "")
        if not password:
            from .backup_vault import load

            password = load(root)["password"]
        if config_path.exists():
            recovery = json.loads(config_path.read_text())
            pem, phrase = unlock(recovery, password)
        else:
            pem, phrase = material(request, state["channel"])
            recovery = envelope(pem, phrase, password, (root / "recovery-public.pem").read_bytes())
        # Establish key correspondence even for an existing envelope, BEFORE a dump.
        envelope(pem, phrase, password, (root / "recovery-public.pem").read_bytes())
        encrypted = backup(root, recovery_envelope=recovery, prune=False)
        with tempfile.TemporaryDirectory(dir=root / "backups", prefix=".verify-") as temp:
            plain = Path(temp) / "verified.tar"
            decrypt(encrypted, plain, pem, phrase)
            restore_check(root, plain)
        receipt_path = encrypted.with_suffix(".sha256.json")
        receipt = json.loads(receipt_path.read_text())
        write_json(receipt_path, {**receipt, "restore_verified": True})
        # Never overwrite an external file, even if one appears after the dialog.
        # A failed copy is labelled .partial; only verified bytes are published.
        partial = target.parent / (target.name + "." + uuid.uuid4().hex + ".partial")
        try:
            with encrypted.open("rb") as source, partial.open("xb") as destination:
                shutil.copyfileobj(source, destination)
                destination.flush()
                os.fsync(destination.fileno())
            if digest(partial) != digest(encrypted):
                raise UnsafeOperation(
                    "A cópia externa falhou a verificação; backup local conservado."
                )
            # Windows rename is no-replace. On POSIX link is atomic no-replace too.
            if os.name == "nt":
                partial.rename(target)
            else:
                os.link(partial, target)
                partial.unlink()
        finally:
            partial.unlink(missing_ok=True)
        if not config_path.exists():
            write_json(config_path, recovery)
            protect(config_path, [("backup", "R")])
        manage(
            root,
            "shell",
            "-c",
            "from inventory.models import AuditEvent; AuditEvent.objects.create(action='native.backup.exported', details="
            + repr(
                {
                    "sha256": digest(target),
                    "authorization": "Windows administrator",
                    "restored_and_verified": True,
                }
            )
            + ")",
        )
        write_json(
            root / ("backup-export-" + uuid.uuid4().hex + ".json"),
            {
                "status": "authenticated-restored-exported",
                "sha256": digest(target),
                "instance": state["instance"],
                "version": state["version"],
            },
        )
        return {"status": "verified", "sha256": digest(target), "size": target.stat().st_size}


def configure_credential(root, request):
    """Configure once, or rebind the SAME envelope after local vault loss."""
    from . import backup_vault

    administrator()
    root = Path(root)
    with exclusive(root):
        if (root / "maintenance.json").exists():
            raise UnsafeOperation("Há manutenção pendente.")
        password = request.get("portable_password", "")
        config = root / "secrets/recovery-envelope.json"
        if config.exists():
            # Never replace an established envelope or silently change its phrase.
            unlock(json.loads(config.read_text()), password)
        else:
            if (root / "secrets" / backup_vault.NAME).exists():
                initial = backup_vault.load(root)
                pem, phrase = initial["pem"].encode(), initial["phrase"]
            else:
                pem, phrase = material(request, read_state(root)["channel"])
            value = envelope(pem, phrase, password, (root / "recovery-public.pem").read_bytes())
            write_json(config, value)
            protect(config, [("backup", "R")])
        backup_vault.save(root, {"password": password})
        return {"status": "configured"}


def credential_status(root):
    from . import backup_vault

    administrator()
    try:
        value = backup_vault.load(root)
        return {"configured": bool(value.get("password")), "bootstrap": bool(value.get("pem"))}
    except UnsafeOperation:
        return {"configured": False, "bootstrap": False}
